import re
import argparse
import json
import requests
from distutils.version import LooseVersion

# https://stackoverflow.com/a/27239645/6943581


def get_versions(package_name):
    url = "https://pypi.org/pypi/{}/json".format(package_name)
    return list(requests.get(url).json()["releases"].keys())


def is_between(ver, min_ver, max_ver):
    try:
        return LooseVersion(ver) >= LooseVersion(min_ver) and LooseVersion(ver) <= LooseVersion(
            max_ver
        )
    except:
        return False


def contains_only_numbers(ver):
    return re.search(r"^[\.\d]+$", ver) is not None


def get_minor_version(ver):
    return re.search(r"^(\d+\.\d+).*", ver).group(1)


def get_minor_versions(versions):
    res = {}

    for ver in versions:
        minor_ver = get_minor_version(ver)
        print(minor_ver)
        if minor_ver not in res:
            res[minor_ver] = ver

    return sorted(list(res.values()))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-name")
    parser.add_argument("--min-ver")
    parser.add_argument("--max-ver")
    return parser.parse_args()


def main():
    args = parse_args()
    versions = get_versions(args.package_name)
    versions = list(filter(contains_only_numbers, versions))
    versions = list(filter(lambda v: is_between(v, args.min_ver, args.max_ver), versions))
    versions = sorted(versions, key=LooseVersion, reverse=True)
    versions = get_minor_versions(versions)
    print(json.dumps({"version": versions}))


if __name__ == "__main__":
    main()
