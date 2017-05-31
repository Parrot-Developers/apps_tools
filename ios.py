# base to build an iOS application
import os
import dragon
import shutil
import re
import tempfile
import tarfile

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

def _xcodebuild(calldir, workspace, configuration, scheme, action, extra_args):
    cmd = "xcodebuild"
    if (dragon.VARIANT == "ios_sim"):
        cmd += " -sdk iphonesimulator -arch x86_64"
    else:
        cmd += " -sdk iphoneos "
    if workspace.endswith("xcworkspace"):
        cmd += " -workspace %s" % workspace
    else:
        cmd += " -project %s" % workspace
    cmd += " -configuration %s" % configuration
    cmd += " -scheme %s" % scheme
    if os.environ.get("MOVE_APPSDATA_IN_OUTDIR"):
        cmd += " -derivedDataPath %s" % os.path.join(dragon.OUT_DIR, "xcodeDerivedData")
    cmd += " %s" % action
    cmd += " ALCHEMY_OUT=%s" % dragon.OUT_DIR
    cmd += " ALCHEMY_OUT_ROOT=%s" % dragon.OUT_ROOT_DIR
    cmd += " ALCHEMY_PRODUCT=%s " % dragon.PRODUCT
    cmd += " ".join(extra_args)
    if not dragon.OPTIONS.verbose and shutil.which("xcpretty"):
        cmd += " | xcpretty && exit ${PIPESTATUS[0]}"
    dragon.exec_cmd(cmd, cwd=calldir)

def add_xcodebuild_task(calldir="", workspace="", configuration="",
                        scheme="", action="", extra_args=[],
                        name="", desc="", subtasks=[], prehook=None):
    dragon.add_meta_task(
        name=name,
        desc=desc,
        subtasks=subtasks,
        prehook=prehook,
        posthook=lambda task, args: _xcodebuild(calldir, workspace,
                                                configuration, scheme,
                                                action, extra_args)
    )

def _jazzy(calldir, workspace, scheme, extra_args):
    cmd = "jazzy"
    cmd += " -x -workspace,%s" % workspace
    cmd += " -x -scheme,%s" % scheme
    outdir = os.path.join(dragon.OUT_DIR, "docs")
    cmd += " -o %s " % outdir
    cmd += " ".join(extra_args)
    dragon.exec_cmd(cmd, cwd=calldir)

def add_jazzy_task(calldir="", workspace="", scheme="", extra_args=[],
                       name="", desc="", subtasks=[]):
    dragon.add_meta_task(
        name=name,
        desc=desc,
        subtasks=subtasks,
        posthook=lambda task, args: _jazzy(calldir, workspace, scheme,
                                           extra_args)
    )

def add_task_build_common():
    dragon.add_alchemy_task(
        name="build-common",
        desc="Build ios common code",
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["all", "sdk"],
        weak=True,
        posthook=lambda task, args: _set_product()
    )

    dragon.add_alchemy_task(
        name="clean-common",
        desc="Clean ios common code",
        product=dragon.PRODUCT,
        variant=dragon.VARIANT,
        defargs=["clobber"],
        weak=True,
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
    <key>compileBitcode</key>
    <true/>
</dict>
</plist>
"""

_release_plist_template="""
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>app-store</string>
    <key>teamID</key>
    <string>{}</string>
</dict>
</plist>
"""

def _create_export_plist(team_id, inhouse=True):
    plist_name = os.path.join(dragon.OUT_DIR, "export.plist")
    with open(plist_name, "w") as f:
        if inhouse:
            template = _inhouse_plist_template
        else:
            template = _release_plist_template
        f.write(template.format(team_id))
    return plist_name

def _replace_app_prefix_in_entitlements(entitlements_path, app_prefix):
    fh, tmp_path = tempfile.mkstemp()
    with open(tmp_path,"w") as f, open(entitlements_path) as ent:
        for l in ent:
            f.write(re.sub(r'(.*<string)>[A-Z0-9]{10}(.com.parrot)',
                           r'\1>{}\2'.format(app_prefix),
                           l))
    os.close(fh)
    os.remove(entitlements_path)
    shutil.move(tmp_path, entitlements_path)

def _export_archive(dirpath, archive_path, scheme, entitlements_path,
                    app_prefix, team_id,
                    inhouse=True):
    if app_prefix is None or team_id is None:
        return None

    export_plist = _create_export_plist(team_id, inhouse=inhouse)
    _replace_app_prefix_in_entitlements(entitlements_path, app_prefix)
    ipa_path = os.path.join(dragon.OUT_DIR, "xcodeApps",
                                "inhouse" if inhouse else "appstore")
    cmd = "xcodebuild -exportArchive -archivePath {} -exportOptionsPlist {}" \
          " -exportPath {}".format(archive_path, export_plist, ipa_path)
    dragon.exec_cmd(cwd=dirpath, cmd=cmd)
    return "{}/{}.ipa".format(ipa_path, scheme)

def _hook_pre_images(task, args):
    # cleanup
    dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="rm -rf images")
    dragon.exec_cmd(cwd=dragon.OUT_DIR, cmd="rm -rf xcodeApps")
    manifest_path = os.path.join(dragon.OUT_DIR, "manifest.xml")
    dragon.gen_manifest_xml(manifest_path)
    task.call_base_pre_hook(args)

def _make_hook_images(calldir, archive_path, scheme,
                     inhouse_app_prefix=None, inhouse_team_id=None,
                     appstore_app_prefix=None, appstore_team_id=None):
    def _hook_images(task, args):
        entitlements_path = os.path.join(archive_path, "Products",
                                         "Applications",
                                         "{}.app".format(scheme),
                                         "archived-expanded-entitlements.xcent")
        inhouse_path = _export_archive(calldir,
                                       archive_path,
                                       scheme,
                                       entitlements_path,
                                       inhouse_app_prefix,
                                       inhouse_team_id,
                                       inhouse=True)
        appstore_path = _export_archive(calldir,
                                        archive_path,
                                        scheme,
                                        entitlements_path,
                                        appstore_app_prefix,
                                        appstore_team_id,
                                        inhouse=False)

        images_dir = os.path.join(dragon.OUT_DIR, "images")
        dragon.makedirs(images_dir)
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
        # Link .ipa
        if inhouse_path:
            dragon.exec_cmd(cwd=images_dir,
                            cmd="ln -s {} {}-inhouse.ipa".format(inhouse_path,
                                                                 scheme))
        if appstore_path:
            dragon.exec_cmd(cwd=images_dir,
                            cmd="ln -s {} {}-appstore.ipa".format(appstore_path,
                                                                  scheme))

        # build.prop
        build_prop_file = os.path.join(dragon.OUT_DIR, "staging", "etc",
                                       "build.prop")
        build_prop_dir = os.path.join(dragon.FINAL_DIR, "etc")
        dragon.makedirs(build_prop_dir)
        dragon.exec_cmd(cwd=build_prop_dir, cmd="cp %s ." % build_prop_file)

        # next hooks
        task.call_base_exec_hook(args)
    return _hook_images

def add_release_task(calldir="", workspace="", configuration="", scheme="",
                     extra_args=[],
                     inhouse_app_prefix=None, inhouse_team_id=None,
                     appstore_app_prefix=None, appstore_team_id=None):
    archive_path = os.path.join(
        dragon.OUT_DIR,
        "xcodeArchives",
        "{}-{}".format(scheme, configuration))

    _args = ["-archivePath {}".format(archive_path)]
    _args.extend(extra_args)
    archive_path += ".xcarchive"

    add_xcodebuild_task(
        name="build-archive",
        desc="build archive for release",
        subtasks=["build-common"],
        prehook=lambda task, args: dragon.exec_cmd(
            cmd="rm -rf {}".format(archive_path)),
        calldir=calldir,
        workspace=workspace,
        configuration=configuration,
        scheme=scheme,
        action="archive",
        extra_args=_args
    )

    dragon.override_meta_task(
        name="images-all",
        prehook=_hook_pre_images,
        exechook=_make_hook_images(calldir, archive_path, scheme,
                                   inhouse_app_prefix, inhouse_team_id,
                                   appstore_app_prefix, appstore_team_id)
    )

    dragon.override_meta_task(
        name="release",
        subtasks=[
            "build-archive",
            "images-all",
            "gen-release-archive"
        ]
    )
