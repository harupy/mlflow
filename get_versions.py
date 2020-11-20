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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-name")
    parser.add_argument("--min-ver")
    parser.add_argument("--max-ver")
    return parser.parse_args()


def main():
    args = parse_args()
    versions = get_versions(args.package_name)
    versions = list(filter(lambda v: re.search(r"\.\d+$", v), versions))
    versions = list(filter(lambda v: is_between(v, args.min_ver, args.max_ver), versions))
    data = {"version": versions}
    print(json.dumps(data))


if __name__ == "__main__":
    main()
