# base to build an iOS application
import os
import dragon
import shutil
import re
import string
import tempfile
import tarfile
import collections

def _get_version_code_from_name(version_name):
    if version_name == "0.0.0" or version_name.startswith("0.0.0-"):
        return "0"
    if not re.match(r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}(-(alpha|beta|rc)+[0-9]{0,2})?$",
                    version_name, flags=re.IGNORECASE):
        raise ValueError("Bad version name : " + version_name)

    try:
        (version, variant) = version_name.split("-")
    except ValueError:
        version = version_name
        variant = "release"
    (major, minor, rev) = (int(x) for x in version.split("."))

    try:
        variant_num = int(variant.strip(string.ascii_letters))
    except ValueError:
        variant_num = 0
    variant_name = variant.strip(string.digits)

    variant_codes = { "alpha": 0,
                      "beta": 1,
                      "rc": 2,
                      "release": 3,
                      }
    try:
        variant_code = variant_codes[variant_name]
    except KeyError:
        variant_code = 0

    return "{:02d}{:02d}{:02d}.{:01d}.{:02d}".format(major, minor, rev,
                                                     variant_code, variant_num)

def _set_product():
    with open(os.path.join(dragon.OUT_ROOT_DIR, "product.xcconfig"), "w") as f:
        f.write("ALCHEMY_PRODUCT = %s\n" % dragon.PRODUCT)

def _xctool(calldir, workspace, configuration, scheme,
            action, reporter, extra_args):
    cmd = "xctool"
    if (dragon.VARIANT == "ios_sim"):
        cmd += " --sdk iphonesimulator --arch x86_64"
    else:
        cmd += " --sdk iphoneos "
    cmd += " --workspace %s" % workspace
    cmd += " --configuration %s" % configuration
    cmd += " --scheme %s" % scheme
    cmd += " --reporter pretty"
    if (reporter):
        cmd += " --reporter %s" % reporter
    cmd += " %s " % action
    cmd += " ".join(extra_args)
    dragon.exec_cmd(cmd, cwd=calldir)

def add_xctool_task(calldir="", workspace="", configuration="",
                    scheme="", action="", reporter=None, extra_args=[],
                    name="", desc="", subtasks=[]):
    dragon.add_meta_task(
        name=name,
        desc=desc,
        subtasks=subtasks,
        posthook=lambda task, args: _xctool(calldir, workspace,
                                            configuration, scheme,
                                            action, reporter,
                                            extra_args)
    )

def _xcodebuild(calldir, workspace, configuration, scheme, action, bundle_id, team_id, extra_args):
    version = dragon.PARROT_BUILD_PROP_VERSION
    vname, _, _ = version.partition('-')
    vcode = _get_version_code_from_name(version)

    # Check if asan is used
    raw_asan = dragon.get_alchemy_var('USE_ADDRESS_SANITIZER')
    if not raw_asan or raw_asan == '0':
        asan = False
    else:
        asan = True

    cmd = "xcodebuild"
    if (dragon.VARIANT == "ios_sim"):
        cmd += " -sdk iphonesimulator -arch x86_64"
    else:
        cmd += " -sdk iphoneos"
    if workspace.endswith("xcworkspace"):
        cmd += " -workspace %s" % workspace
    else:
        cmd += " -project %s" % workspace
    cmd += " -configuration %s" % configuration
    cmd += " -scheme %s" % scheme
    cmd += " -allowProvisioningUpdates"
    if os.environ.get("MOVE_APPSDATA_IN_OUTDIR"):
        cmd += " -derivedDataPath %s" % os.path.join(dragon.OUT_DIR, "xcodeDerivedData")
    if asan:
        cmd += " -enableAddressSanitizer YES"
    cmd += " %s" % action
    cmd += " ALCHEMY_OUT=%s" % dragon.OUT_DIR
    cmd += " ALCHEMY_OUT_ROOT=%s" % dragon.OUT_ROOT_DIR
    cmd += " ALCHEMY_PRODUCT=%s" % dragon.PRODUCT
    if bundle_id:
        cmd += " APP_BUNDLE_IDENTIFIER=%s" % bundle_id
    if team_id:
        cmd += " DEVELOPMENT_TEAM=%s" % team_id
    cmd += " APP_VERSION_SHORT=%s" % vname
    cmd += " APP_VERSION=%s" % version
    cmd += " APP_BUILD=%s " % vcode
    cmd += " ".join(extra_args)
    if not dragon.OPTIONS.verbose and shutil.which("xcpretty"):
        cmd += " | xcpretty && exit ${PIPESTATUS[0]}"
    dragon.exec_cmd(cmd, cwd=calldir)

def add_xcodebuild_task(*, calldir="", workspace="", configuration="",
                        scheme="", action="", bundle_id=None, team_id=None,
                         extra_args=[], **kwargs):
    dragon.add_meta_task(
        posthook=lambda task, args: _xcodebuild(calldir, workspace,
                                                configuration, scheme,
                                                action, bundle_id, team_id,
                                                extra_args),
        **kwargs
    )

def _jazzy(calldir, scheme, extra_args):
    cmd = "jazzy"
    cmd += " -x -scheme,%s" % scheme
    outdir = os.path.join(dragon.OUT_DIR, "docs")
    cmd += " -o %s " % outdir
    cmd += " ".join(extra_args)
    dragon.exec_cmd(cmd, cwd=calldir)

def add_jazzy_task(*, calldir="", scheme="", extra_args=[], **kwargs):
    dragon.add_meta_task(
        posthook=lambda task, args: _jazzy(calldir, scheme, extra_args),
        **kwargs
    )

def add_task_build_common():
    dragon.add_alchemy_task(
        name="build-common",
        desc="Build ios common code",
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["all", "sdk"],
        weak=True,
        posthook=lambda task, args: _set_product(),
        secondary_help=True
    )

    dragon.add_alchemy_task(
        name="clean-common",
        desc="Clean ios common code",
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["clobber"],
        weak=True,
        secondary_help=True
    )

_inhouse_plist_template="""
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>enterprise</string>
    <key>teamID</key>
    <string>{}</string>
    <key>provisioningProfiles</key>
    <dict>
        <key>{}</key>
        <string>{}</string>
    </dict>
    <key>compileBitcode</key>
    <true/>
</dict>
</plist>
"""

def _create_export_plist(signing_infos, bundle_id):
    plist_name = os.path.join(dragon.OUT_DIR, "export.plist")
    with open(plist_name, "w") as f:
        template = _inhouse_plist_template
        f.write(template.format(signing_infos.team_id, bundle_id, signing_infos.profile))
    return plist_name

def _export_archive(dirpath, archive_path, app):
    signing_infos = app.inhouse_infos
    if signing_infos is None:
        return None

    export_plist = _create_export_plist(signing_infos, app.bundle_id)
    ipa_path = os.path.join(dragon.OUT_DIR, "xcodeApps", "temp")
    ipa_out_path = os.path.join(dragon.OUT_DIR, "xcodeApps", "inhouse")
    cmd = "xcodebuild -exportArchive -archivePath {} -exportOptionsPlist {} -allowProvisioningUpdates" \
          " -exportPath {}".format(archive_path, export_plist, ipa_path)
    dragon.exec_cmd(cwd=dirpath, cmd=cmd)
    ipa_raw_path = "{}/{}.ipa".format(ipa_path, app.scheme)
    os.makedirs(ipa_out_path, exist_ok=True)
    ipa_final_path = "{}/{}".format(ipa_out_path, app.ipa_name)
    os.rename(ipa_raw_path, ipa_final_path)
    return ipa_final_path

def _hook_pre_images(task, args):
    # cleanup
    dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="rm -rf images")
    dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="rm -rf xcodeApps")
    manifest_path = os.path.join(dragon.OUT_DIR, "manifest.xml")
    dragon.gen_manifest_xml(manifest_path)
    task.call_base_pre_hook(args)


SignatureInfos = collections.namedtuple('SignatureInfos', ['app_prefix', 'team_id', 'profile'])

class App:

    _app_id = 0

    def __init__(self, scheme, configuration, bundle_id, *, args=[], inhouse_infos=None, display_name=None, build_team_id=None):
        self.configuration = configuration
        self.scheme = scheme
        self.bundle_id = bundle_id
        self.args = args
        self.inhouse_infos = inhouse_infos
        self.build_team_id = build_team_id
        if display_name:
            self.name = display_name
            self.ipa_name = "{}.ipa".format(display_name)
        else:
            if App._app_id > 0:
                self.name = "{}-{}-{}".format(self.scheme,
                                              self.configuration,
                                              App._app_id)
                self.ipa_name = "{}-{}-inhouse.ipa".format(self.scheme,
                                                           App._app_id)
            else:
                self.name = "{}-{}".format(self.scheme, self.configuration)
                self.ipa_name = "{}-inhouse.ipa".format(self.scheme)
            App._app_id += 1

    def _archivePath(self, out, skipExt=False):
        path = os.path.join(out, "xcodeArchives", self.name)
        if skipExt:
            return path
        return "{}{}".format(path, ".xcarchive")

    def _taskName(self):
        return "build-archive-{}".format(self.name)
    def _taskDesc(self):
        return "build archive {} for release".format(self.name)

def _make_hook_images(calldir, apps):
    def _hook_images(task, args):

        images_dir = os.path.join(dragon.OUT_DIR, "images")
        dragon.makedirs(images_dir)

        for app in apps:
            archive_path = app._archivePath(dragon.OUT_DIR)
            # Compress .xcarchive
            archive_dir = os.path.dirname(archive_path)
            archive_name = os.path.basename(archive_path)
            tarname = os.path.join(
                images_dir,
                "{}.tar.gz".format(os.path.basename(archive_path)))
            cwd = os.getcwd()
            os.chdir(archive_dir)
            tar = tarfile.open(tarname, "w:gz")
            tar.add(archive_name)
            tar.close()
            os.chdir(cwd)

            inhouse_path = _export_archive(calldir,
                                           archive_path,
                                           app)
            # Link .ipa
            if inhouse_path:
                dragon.exec_cmd(cwd=images_dir,
                                cmd="ln -s {} {}".format(inhouse_path,
                                                         app.ipa_name))

        # build.prop
        build_prop_file = os.path.join(dragon.OUT_DIR, "staging", "etc",
                                       "build.prop")
        dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="cp %s ." % build_prop_file)

        # next hooks
        task.call_base_exec_hook(args)
    return _hook_images

def _make_rm_previous_archive(app):
    def _rm_previous_archive(task, args):
        dragon.exec_cmd('rm -rf {}'.format(app._archivePath(dragon.OUT_DIR)))
    return _rm_previous_archive


def add_release_task(*, calldir="", workspace="", apps=[], extra_tasks=[], build_common_task='build-common'):
    subtasks = []
    for app in apps:
        _args = ["-archivePath {}".format(app._archivePath(dragon.OUT_DIR, skipExt=True))]
        if app.args:
            _args.extend(app.args)

        add_xcodebuild_task(
            name=app._taskName(),
            desc=app._taskDesc(),
            subtasks=[build_common_task],
            prehook=_make_rm_previous_archive(app),
            calldir=calldir,
            workspace=workspace,
            configuration=app.configuration,
            scheme=app.scheme,
            bundle_id=app.bundle_id,
            action="archive",
            team_id=app.build_team_id,
            extra_args=_args,
            secondary_help=True
        )
        subtasks.append(app._taskName())

    dragon.override_meta_task(
        name="images-all",
        prehook=_hook_pre_images,
        exechook=_make_hook_images(calldir, apps)
    )

    subtasks.append("images-all")
    subtasks.extend(extra_tasks)
    subtasks.append("gen-release-archive")

    dragon.override_meta_task(
        name="release",
        subtasks=subtasks
    )
