import dragon


def get_version_code(version, *, use_dots=False):
    if version.major == 0 and version.minor == 0 and version.patch == 0:
        return "1"

    if (version.major >= 100 or
        version.minor >= 100 or
        version.patch >= 100 or
            version.build >= 100):
        raise ValueError("Invalid version: {}".format(version))

    variant_codes = {
        dragon.Version.TYPE_ALPHA: 0,
        dragon.Version.TYPE_BETA: 1,
        dragon.Version.TYPE_RC: 2,
        dragon.Version.TYPE_RELEASE: 3,
    }

    if not use_dots:
        code = "{:02d}{:02d}{:02d}{:01d}{:02d}".format(version.major, version.minor, version.patch,
                                                       variant_codes[version.type], version.build)
    else:
        code = "{:02d}{:02d}{:02d}.{:01d}.{:02d}".format(version.major, version.minor, version.patch,
                                                         variant_codes[version.type], version.build)
    return code.lstrip("0")
