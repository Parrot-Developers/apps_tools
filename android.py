# base to build an Android application
import os
import logging
import re
import string
import dragon
import shutil
import sys

import apps_tools.common as common


class _ndk_version:
    def __init__(self, name, minor=0):
        if isinstance(name, str):
            self._parse(name)
        else:
            self.major = name
            self.minor = minor

    def _parse(self, name):
        if name.startswith("r"):
            name = name[1:]
        self.major = int(name[:2])
        name = name[2:]
        if name:
            self.minor = string.ascii_lowercase.index(name[0])
        else:
            self.minor = 0

    def __repr__(self):
        if self.minor > 0:
            return "r{}{}".format(self.major,
                                  string.ascii_lowercase[self.minor])
        return "r{}".format(self.major)

    def __eq__(self, other):
        return self.major == other.major and self.minor == other.minor

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        if self.major < other.major:
            return True
        if self.major == other.major and self.minor < other.minor:
            return True
        return False

    def __gt__(self, other):
        if self.major > other.major:
            return True
        if self.major == other.major and self.minor > other.minor:
            return True
        return False

    def __le__(self, other):
        return not self.__gt__(other)

    def __ge__(self, other):
        return not self.__lt__(other)


def _get_ndk_version(min_version=None, max_version=None, source="apps_tools"):
    try:
        ndkPath = os.environ["ANDROID_NDK_PATH"]
    except KeyError:
        logging.error("ANDROID_NDK_PATH needs to be defined")
        sys.exit(1)
    propFile = os.path.join(ndkPath, "source.properties")
    with open(propFile, 'r') as f:
        for line in f:
            if "Pkg.Revision" not in line:
                continue
            _, _, v = line.partition("=")
            v = v.strip()
    version = v.split('.')
    try:
        version = [int(x) for x in version[:2]]
        version = _ndk_version(version[0], version[1])
    except ValueError:
        logging.error("Unable to read android ndk version")
        sys.exit(1)
    if min_version is not None and version < min_version:
        logging.error("NDK {} is too old for {}. Expected at least {}".format(
            version, source, min_version))
        sys.exit(1)
    if max_version is not None and version >= max_version:
        logging.error("NDK {} is too recent for {}.".format(version, source) +
                      " First KO version is {}".format(max_version))
        sys.exit(1)
    return version


_NDK_VERSION = None


def _init():
    global _NDK_VERSION
    if _NDK_VERSION is None:
        _NDK_VERSION = _get_ndk_version(min_version=_ndk_version(14, 1),
                                        max_version=_ndk_version(19, 0))
        logging.info("Installed NDK version: {}".format(_NDK_VERSION))


def check_ndk_version(min_version=None, max_version=None):
    _init()
    minv = _ndk_version(min_version) if min_version else None
    maxv = _ndk_version(max_version) if max_version else None
    _get_ndk_version(minv, maxv, source="product")


def setup_argparse(parser):
    parser.add_argument("--abis",
                        dest="android_abis",
                        nargs="+",
                        choices=("armeabi", "armeabi-v7a", "arm64-v8a",
                                 "mips", "mips64",
                                 "x86", "x86_64"),
                        help="Select which android ABIS to build")


def _setup_android_abi(task, args, abi):
    task.call_base_pre_hook(args)
    task.extra_env["ANDROID_ABI"] = abi

# Address sanitizer setup/cleanup


def _gen_asan_wrapper(abi, lib_dir, script_dir):
    wrap_template = """#!/system/bin/sh
HERE="$(cd "$(dirname "$0")" && pwd)"
export ASAN_OPTIONS=log_to_syslog=false,allow_user_segv_handler=1
export LD_PRELOAD=$HERE/libclang_rt.asan-{}-android.so
$@"""
    abi_filter = {
        'arm64-v8a': 'aarch64',
        'armeabi': 'arm',
        'armeabi-v7a': 'arm',
        'x86': 'i686',
    }
    raw_abi = abi
    if abi in abi_filter:
        abi = abi_filter[abi]
    os.makedirs(lib_dir, exist_ok=True)
    os.makedirs(script_dir, exist_ok=True)

    asan_lib_fname = "libclang_rt.asan-{}-android.so".format(abi)
    clang_path = os.path.join(dragon.OUT_DIR, raw_abi, "toolchain",
                              "lib64", "clang")
    if not os.path.isdir(clang_path):
        logging.info("Unable to find clang path while setting asan_wrapper")
        return

    clang_versions = os.listdir(path=clang_path)
    if not clang_versions:
        logging.info("Unable to get clang version while setting asan_wrapper")
        return

    cc_version = clang_versions[0]
    asan_lib_path = os.path.join(clang_path, cc_version, "lib",
                                 "linux", asan_lib_fname)

    shutil.copyfile(asan_lib_path, os.path.join(lib_dir, asan_lib_fname))

    with open(os.path.join(script_dir, "wrap.sh"), "w") as f:
        f.write(wrap_template.format(abi))


def _asan_setup(abi):
    asan_out_dir = os.path.join(dragon.OUT_DIR, "asan")
    asan_lib_dir = os.path.join(asan_out_dir, "libs", abi)
    asan_script_dir = os.path.join(asan_out_dir, "scripts", "lib", abi)
    _gen_asan_wrapper(abi, asan_lib_dir, asan_script_dir)


def _asan_clean(abi):
    asan_out_dir = os.path.join(dragon.OUT_DIR, "asan")
    asan_lib_dir = os.path.join(asan_out_dir, "libs", abi)
    asan_script_dir = os.path.join(asan_out_dir, "scripts", "lib", abi)
    if os.path.exists(asan_lib_dir):
        shutil.rmtree(asan_lib_dir)
    if os.path.exists(asan_script_dir):
        shutil.rmtree(asan_script_dir)

# Register a task to build android common code for a specific abi/arch


def _add_android_abi(abi, asan=False):

    # Create asan wrapper scripts if required
    asan_build_func = _asan_setup if asan else _asan_clean

    dragon.add_alchemy_task(
        name="build-common-{}".format(abi),
        desc="Build android common for {}".format(abi),
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["all", "sdk"],
        prehook=lambda task, args: _setup_android_abi(task, args, abi),
        posthook=lambda task, args: asan_build_func(abi),
        weak=True,
        outsubdir=abi,
        host_in_subdir=False,
        secondary_help=True
    )

    dragon.add_alchemy_task(
        name="clean-common-{}".format(abi),
        desc="Clean android common for {}".format(abi),
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["clobber"],
        prehook=lambda task, args: _setup_android_abi(task, args, abi),
        posthook=lambda task, args: _asan_clean(abi),
        weak=True,
        outsubdir=abi,
        host_in_subdir=False,
        secondary_help=True
    )


def _ndk_build(calldir, module, abis, extra_args, ignore_failure=False):

    # Check if asan is used
    raw_asan = dragon.get_alchemy_var('USE_ADDRESS_SANITIZER')
    if not raw_asan or raw_asan == '0':
        asan = False
    else:
        asan = True

    outdir = os.path.join(dragon.OUT_DIR, "jni", module)
    args = "NDK_OUT=%s" % os.path.join(outdir, "obj")
    args += " NDK_LIBS_OUT=%s" % os.path.join(outdir, "libs")
    args += " PRODUCT_DIR=%s" % os.path.join(dragon.WORKSPACE_DIR,
                                             "products", dragon.PRODUCT,
                                             dragon.VARIANT)
    args += " PRODUCT_OUT_DIR=%s" % dragon.OUT_DIR
    args += ' APP_ABI="%s"' % " ".join(abis)
    if asan:
        args += " LOCAL_ALLOW_UNDEFINED_SYMBOLS=true"
    if dragon.OPTIONS.verbose:
        args += " V=1"
    args += " -j%d " % dragon.OPTIONS.jobs.job_num
    args += " ".join(extra_args)
    cmd = "${ANDROID_NDK_PATH}/ndk-build %s" % args
    try:
        dragon.exec_cmd(cmd=cmd, cwd=calldir)
    except dragon.ExecError:
        if not ignore_failure:
            raise


def add_ndk_build_task(*, calldir="", module="", abis=[], extra_args=[],
                       ignore_failure=False, **kwargs):
    _init()
    if dragon.OPTIONS.android_abis:
        abis = dragon.OPTIONS.android_abis
    dragon.add_meta_task(
        posthook=lambda task, dragon_args: _ndk_build(calldir, module, abis,
                                                      extra_args,
                                                      ignore_failure),
        **kwargs
    )


def _gradle(calldir, abis, extra_args):
    version = dragon.PARROT_BUILD_PROP_VERSION
    vname, _, suffix = version.partition('-')
    vcode = common.get_version_code(dragon.PARROT_BUILD_VERSION)

    cmd = "./gradlew"
    if os.environ.get("MOVE_APPSDATA_IN_OUTDIR"):
        cmd += " --project-cache-dir %s" % os.path.join(dragon.OUT_DIR,
                                                        ".gradle")
    cmd += " -PalchemyOutRoot=%s" % dragon.OUT_ROOT_DIR
    cmd += " -PalchemyOut=%s" % dragon.OUT_DIR
    cmd += " -PalchemyProduct=%s" % dragon.PRODUCT
    if abis:
        cmd += ' -PappAbis="%s"' % " ".join(abis)
    cmd += " -PappVersionName=%s" % vname
    if suffix:
        cmd += " -PappVersionNameSuffix=-%s" % suffix
    cmd += " -PappVersionCode=%s " % vcode
    cmd += " ".join(extra_args)
    dragon.exec_cmd(cmd, cwd=calldir)


def add_gradle_task(*, calldir, target="", abis=[], extra_args=[], **kwargs):
    _init()
    if dragon.OPTIONS.android_abis:
        abis = dragon.OPTIONS.android_abis
    _args = [target]
    _args.extend(extra_args)
    dragon.add_meta_task(
        posthook=lambda task, dragon_args: _gradle(calldir, abis, _args),
        **kwargs
    )


def _hook_alchemy_genproject_android(task, args, abi):
    script_path = os.path.join(dragon.ALCHEMY_HOME, "scripts",
                               "genproject", "genproject.py")
    subscript_name = task.name.replace("gen", "")

    if "-h" in args or "--help" in args:
        dragon.exec_cmd("%s %s -h" % (script_path, subscript_name))
        dragon.LOGW(
            "Note: The -b option and dump_xml file are automatically given.")
        raise dragon.TaskExit()

    dragon.exec_cmd(cmd="./build.sh -p %s-%s --abis %s -A dump-xml" %
                    (dragon.PRODUCT, dragon.VARIANT, abi))
    dump_xml = os.path.join(dragon.OUT_DIR, abi, "alchemy-database.xml")
    cmd_args = [script_path, subscript_name,
                "-b", "'-p %s-%s --abis %s -A'" % (
                    dragon.PRODUCT, dragon.VARIANT, abi),
                dump_xml, " ".join(args)]
    dragon.exec_cmd(" ".join(cmd_args))


def add_task_build_common(android_abis, default_abi=None):
    _init()
    if dragon.OPTIONS.android_abis:
        android_abis = dragon.OPTIONS.android_abis

    # Check if asan is used
    raw_asan = dragon.get_alchemy_var('USE_ADDRESS_SANITIZER')
    if not raw_asan or raw_asan == '0':
        asan = False
    else:
        asan = True

    # Register all abi/arch\
    for abi in android_abis:
        _add_android_abi(abi, asan)

    # Update basic alchemy task to use default abi
    if not default_abi:
        default_abi = android_abis[0]
    if default_abi not in android_abis:
        logging.error("Default android abi(%s) is not in %s",
                      default_abi, android_abis)
    else:
        dragon.override_alchemy_task("alchemy",
                                     prehook=lambda task, args:
                                     _setup_android_abi(task, args,
                                                        default_abi),
                                     outsubdir=default_abi,
                                     host_in_subdir=False)

    # Override genproject tasks
    gen_tasks = {
        "geneclipse": "Generate Eclipse CDT project",
        "genqtcreator": "Generate QtCreator project",
        "genvscode": "Generate VisualStudio Code project",
    }
    for taskname, taskdesc in gen_tasks.items():
        dragon.override_meta_task(
            name=taskname,
            desc=taskdesc,
            exechook=lambda task, args: _hook_alchemy_genproject_android(
                task, args, default_abi)
        )

    # Meta-task to build all common code abi/arch
    dragon.add_meta_task(
        name="build-common",
        desc="Build android common code for all architectures",
        subtasks=["build-common-" + abi for abi in android_abis],
        weak=True,
        secondary_help=True
    )
    dragon.add_meta_task(
        name="clean-common",
        desc="Clean android common code for all architectures",
        subtasks=["clean-common-" + abi for abi in android_abis],
        weak=True,
        secondary_help=True
    )


def _hook_pre_images(task, args):
    # cleanup
    dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="rm -rf images")
    manifest_path = os.path.join(dragon.OUT_DIR, "manifest.xml")
    dragon.gen_manifest_xml(manifest_path)
    task.call_base_pre_hook(args)


class App:
    def __init__(self, apk_file):
        self.apk_file = apk_file


def _make_hook_images(symbols_path, apps, def_abi):
    def _hook_images(task, args):
        # tar symbols
        symbols_file = os.path.join(dragon.OUT_DIR,
                                    "symbols-%s-%s.tar" %
                                    (dragon.PRODUCT, dragon.VARIANT))
        dragon.exec_cmd(cwd=symbols_path,
                        cmd="find . -name \"*.so\" | tar -cv -f " +
                        symbols_file +
                        " --files-from -")

        # link apk(s)
        images_dir = os.path.join(dragon.OUT_DIR, "images")
        dragon.makedirs(images_dir)
        for app in apps:
            dragon.exec_cmd(cwd=images_dir,
                            cmd="ln -s {} .".format(app.apk_file))

        # build.prop
        build_prop_file = os.path.join(dragon.OUT_DIR, def_abi,
                                       "staging", "etc", "build.prop")
        dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="cp %s ." % build_prop_file)

        # global.config
        global_config_file = os.path.join(dragon.OUT_DIR, def_abi,
                                          "global.config")
        dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="cp %s ." % global_config_file)

        # next hooks
        task.call_base_exec_hook(args)
    return _hook_images


def add_release_task(symbols_path, apps, default_abi, *,
                     extra_tasks=[], build_task='build'):
    _init()
    if dragon.OPTIONS.android_abis:
        default_abi = dragon.OPTIONS.android_abis[0]

    dragon.override_meta_task(
        name="images-all",
        prehook=_hook_pre_images,
        exechook=_make_hook_images(symbols_path, apps, default_abi)
    )

    subtasks = [
        build_task,
        "images-all"
    ]
    subtasks.extend(extra_tasks)
    subtasks.append("gen-release-archive")

    dragon.override_meta_task(
        name="release",
        subtasks=subtasks
    )
