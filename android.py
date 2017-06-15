# base to build an Android application
import os, logging
import dragon

def _setup_android_abi(task, args, abi):
    task.call_base_pre_hook(args)
    task.extra_env["ANDROID_ABI"] = abi

# Register a task to build android common code for a specific abi/arch
def _add_android_abi(abi):
    dragon.add_alchemy_task(
        name="build-common-{}".format(abi),
        desc="Build android common for {}".format(abi),
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["all", "sdk"],
        prehook=lambda task, args: _setup_android_abi(task, args, abi),
        weak=True,
        outsubdir=abi
    )

    dragon.add_alchemy_task(
        name="clean-common-{}".format(abi),
        desc="Clean android common for {}".format(abi),
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["clobber"],
        prehook=lambda task, args: _setup_android_abi(task, args, abi),
        weak=True,
        outsubdir=abi
    )

def _ndk_build(calldir, module, abis, extra_args, ignore_failure=False):
    outdir = os.path.join(dragon.OUT_DIR, "jni", module)
    args = "NDK_OUT=%s" % os.path.join(outdir, "obj")
    args += " NDK_LIBS_OUT=%s" % os.path.join(outdir, "libs")
    args += " PRODUCT_DIR=%s" % os.path.join(dragon.WORKSPACE_DIR,
      "products", dragon.PRODUCT, dragon.VARIANT)
    args += " PRODUCT_OUT_DIR=%s" % dragon.OUT_DIR
    args += " APP_ABI=\"%s\"" % " ".join(abis)
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

def add_ndk_build_task(calldir="", module="", abis=[], extra_args=[],
                       name="", desc="", subtasks=[], ignore_failure=False):
    dragon.add_meta_task(
        name=name,
        desc=desc,
        subtasks=subtasks,
        posthook=lambda task, dragon_args: _ndk_build(calldir, module, abis,
                                                      extra_args,
                                                      ignore_failure)
    )

def _gradle(calldir, extra_args):
    cmd = "./gradlew"
    if os.environ.get("MOVE_APPSDATA_IN_OUTDIR"):
        cmd +=" --project-cache-dir %s" % os.path.join(dragon.OUT_DIR,
                                                       ".gradle")
    cmd +=" -PalchemyOutRoot=%s" % dragon.OUT_ROOT_DIR
    cmd +=" -PalchemyOut=%s" % dragon.OUT_DIR
    cmd +=" -PalchemyProduct=%s " % dragon.PRODUCT
    cmd +=" ".join(extra_args)
    dragon.exec_cmd(cmd, cwd=calldir)

def add_gradle_task(calldir, target="", extra_args=[],
                    name="", desc="", subtasks=[]):
    _args = [target]
    _args.extend(extra_args)
    dragon.add_meta_task(
        name=name,
        desc=desc,
        subtasks=subtasks,
        posthook=lambda task, dragon_args: _gradle(calldir, _args)
    )

def add_task_build_common(android_abis, default_abi=None):
    # Register all abi/arch\
    for abi in android_abis:
        _add_android_abi(abi)

    # Update basic alchemy task to use default abi
    if not default_abi:
        default_abi = android_abis[0]
    if default_abi not in android_abis:
        logging.error("Default android abi(%s) is not in %s", default_abi, android_abis)
    else:
        dragon.override_alchemy_task("alchemy",
                prehook=lambda task, args: _setup_android_abi(task, args, default_abi),
                outsubdir=default_abi)

    # Meta-task to build all common code abi/arch
    dragon.add_meta_task(
        name="build-common",
        desc="Build android common code for all architectures",
        subtasks=["build-common-" + abi for abi in android_abis],
        weak=True
    )
    dragon.add_meta_task(
        name="clean-common",
        desc="Clean android common code for all architectures",
        subtasks=["clean-common-" + abi for abi in android_abis],
        weak=True
    )

def _hook_pre_images(task, args):
    # cleanup
    dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="rm -rf images")
    manifest_path = os.path.join(dragon.OUT_DIR, "manifest.xml")
    dragon.gen_manifest_xml(manifest_path)
    task.call_base_pre_hook(args)

def _make_hook_images(symbols_path, apk_dir, apk_files, abis):
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
        apk_files_ext = [ os.path.join(apk_dir, x) for x in apk_files ]
        cmd = "ln -s " + " ".join(apk_files_ext) + " ."
        dragon.exec_cmd(cwd=images_dir, cmd=cmd)

        # build.prop
        build_prop_file = os.path.join(dragon.OUT_DIR, abis[-1],
                                       "staging", "etc", "build.prop")
        dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="cp %s ." % build_prop_file)

        # global.config
        global_config_file = os.path.join(dragon.OUT_DIR, abis[-1],
                                          "global.config")
        dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="cp %s ." % global_config_file)

        # next hooks
        task.call_base_exec_hook(args)
    return _hook_images

def add_release_task(symbols_path, apk_dir, apk_files, abis):

    dragon.override_meta_task(
        name="images-all",
        prehook=_hook_pre_images,
        exechook=_make_hook_images(symbols_path,
                                     apk_dir,
                                     apk_files,
                                     abis)
    )

    dragon.override_meta_task(
        name="release",
        subtasks=[
            "build",
            "images-all",
            "gen-release-archive"
        ]
    )
