#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import gzip
import sys
import glob
import logging
import collections
from optparse import OptionParser
import memcache#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import gzip
import sys
import glob
import logging
import collections
from optparse import OptionParser
import memcache
import appsinstalled_pb2
from multiprocessing import Pool

NORMAL_ERR_RATE = 0.01
AppsInstalled = collections.namedtuple(
    "AppsInstalled", ["dev_type", "dev_id", "lat", "lon", "apps"]
)


def dot_rename(path):
    """Rename a file by prefixing it with a dot."""
    head, fn = os.path.split(path)
    os.rename(path, os.path.join(head, "." + fn))


def insert_appsinstalled(memc_addr, appsinstalled, dry_run=False, memc_clients=None):
    """Insert apps installed data into memcached."""
    ua = appsinstalled_pb2.UserApps()
    ua.lat = appsinstalled.lat
    ua.lon = appsinstalled.lon
    key = f"{appsinstalled.dev_type}:{appsinstalled.dev_id}"
    ua.apps.extend(appsinstalled.apps)
    packed = ua.SerializeToString()

    try:
        if dry_run:
            logging.debug(f"{memc_addr} - {key} -> {str(ua).replace('\n', ' ')}")
        else:
            if memc_clients is not None:
                memc = memc_clients.get(memc_addr)
                if memc is None:
                    memc = memcache.Client([memc_addr], socket_timeout=1)
                    memc_clients[memc_addr] = memc
            else:
                memc = memcache.Client([memc_addr], socket_timeout=1)
            memc.set(key, packed)
    except Exception as e:
        logging.exception(f"Cannot write to memc {memc_addr}: {e}")
        return False

    return True


def parse_appsinstalled(line):
    """Parse a line of input into an AppsInstalled namedtuple."""
    line_parts = line.strip().split("\t")
    if len(line_parts) < 5:
        return None

    dev_type, dev_id, lat, lon, raw_apps = line_parts
    if not dev_type or not dev_id:
        return None

    try:
        apps = [int(a.strip()) for a in raw_apps.split(",")]
    except ValueError:
        apps = [int(a.strip()) for a in raw_apps.split(",") if a.isdigit()]
        logging.info(f"Not all user apps are digits: `{line}`")

    try:
        lat, lon = float(lat), float(lon)
    except ValueError:
        logging.info(f"Invalid geo coords: `{line}`")
        return None  # Возвращаем None, если координаты некорректны

    return AppsInstalled(dev_type, dev_id, lat, lon, apps)


def process_file(args):
    """Process a single file and insert apps installed data into memcached."""
    fn, device_memc, options = args
    processed = errors = 0
    logging.info(f"Processing {fn}")

    with gzip.open(fn, "rt") as fd:  # Используем режим "rt" для чтения как текста
        memc_clients = {}
        if not options.dry:
            for memc_addr in set(device_memc.values()):
                memc_clients[memc_addr] = memcache.Client([memc_addr], socket_timeout=1)

        for line in fd:
            line = line.strip()
            if not line:
                continue

            appsinstalled = parse_appsinstalled(line)
            if not appsinstalled:
                errors += 1
                continue

            memc_addr = device_memc.get(appsinstalled.dev_type)
            if not memc_addr:
                errors += 1
                logging.error(f"Unknown device type: {appsinstalled.dev_type}")
                continue

            ok = insert_appsinstalled(memc_addr, appsinstalled, options.dry, memc_clients=memc_clients)
            if ok:
                processed += 1
            else:
                errors += 1

    if not processed:
        dot_rename(fn)
        return

    err_rate = float(errors) / processed
    if err_rate < NORMAL_ERR_RATE:
        logging.info(f"Acceptable error rate ({err_rate}). Successfully loaded")
    else:
        logging.error(f"High error rate ({err_rate} > {NORMAL_ERR_RATE}). Failed to load {fn}")

    dot_rename(fn)


def main(options):
    """Main function to run the application."""
    device_memc = {
        "idfa": options.idfa,
        "gaid": options.gaid,
        "adid": options.adid,
        "dvid": options.dvid,
    }

    files = glob.glob(options.pattern, recursive=True)  # Добавляем recursive=True
    logging.info(f"Found files: {files}")  # Отладочное сообщение

    if not files:
        logging.error(f"No files found matching pattern: {options.pattern}")
        sys.exit(1)

    args = [(fn, device_memc, options) for fn in files]

    with Pool() as pool:
        pool.map(process_file, args)


def prototest():
    """Run a prototype test."""
    sample = "idfa\t1rfw452y52g2gq4g\t55.55\t42.42\t1423,43,567,3,7,23\ngaid\t7rfw452y52g2gq4g\t55.55\t42.42\t7423,424"

    for line in sample.splitlines():
        dev_type, dev_id, lat, lon, raw_apps = line.strip().split("\t")
        apps = [int(a) for a in raw_apps.split(",") if a.isdigit()]
        lat, lon = float(lat), float(lon)
        ua = appsinstalled_pb2.UserApps()
        ua.lat = lat
        ua.lon = lon
        ua.apps.extend(apps)
        packed = ua.SerializeToString()
        unpacked = appsinstalled_pb2.UserApps()
        unpacked.ParseFromString(packed)
        assert ua == unpacked


if __name__ == "__main__":
    op = OptionParser()
    op.add_option("-t", "--test", action="store_true", default=False)
    op.add_option("-l", "--log", action="store", default=None)
    op.add_option("--dry", action="store_true", default=False)
    op.add_option("--pattern", action="store", default="/data/appsinstalled/*.tsv.gz")
    op.add_option("--idfa", action="store", default="127.0.0.1:33013")
    op.add_option("--gaid", action="store", default="127.0.0.1:33014")
    op.add_option("--adid", action="store", default="127.0.0.1:33015")
    op.add_option("--dvid", action="store", default="127.0.0.1:33016")

    (opts, args) = op.parse_args()

    logging.basicConfig(
        filename=opts.log,
        level=logging.INFO if not opts.dry else logging.DEBUG,
        format="[%(asctime)s] %(levelname).1s %(process)d %(message)s",
        datefmt="%Y.%m.%d %H:%M:%S",
    )

    if opts.test:
        prototest()
        sys.exit(0)

    logging.info(f"Memc loader started with options: {opts}")

    try:
        main(opts)
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        sys.exit(1)

import appsinstalled_pb2
from multiprocessing import Pool

NORMAL_ERR_RATE = 0.01
AppsInstalled = collections.namedtuple(
    "AppsInstalled", ["dev_type", "dev_id", "lat", "lon", "apps"]
)


def dot_rename(path):
    """Rename a file by prefixing it with a dot."""
    head, fn = os.path.split(path)
    os.rename(path, os.path.join(head, "." + fn))


def insert_appsinstalled(memc_addr, appsinstalled, dry_run=False, memc_clients=None):
    """Insert apps installed data into memcached."""
    ua = appsinstalled_pb2.UserApps()
    ua.lat = appsinstalled.lat
    ua.lon = appsinstalled.lon
    key = f"{appsinstalled.dev_type}:{appsinstalled.dev_id}"
    ua.apps.extend(appsinstalled.apps)
    packed = ua.SerializeToString()

    try:
        if dry_run:
            logging.debug(f"{memc_addr} - {key} -> {str(ua).replace('\n', ' ')}")
        else:
            if memc_clients is not None:
                memc = memc_clients.get(memc_addr)
                if memc is None:
                    memc = memcache.Client([memc_addr], socket_timeout=1)
                    memc_clients[memc_addr] = memc
            else:
                memc = memcache.Client([memc_addr], socket_timeout=1)
            memc.set(key, packed)
    except Exception as e:
        logging.exception(f"Cannot write to memc {memc_addr}: {e}")
        return False

    return True


def parse_appsinstalled(line):
    """Parse a line of input into an AppsInstalled namedtuple."""
    line_parts = line.strip().split("\t")
    if len(line_parts) < 5:
        return None

    dev_type, dev_id, lat, lon, raw_apps = line_parts
    if not dev_type or not dev_id:
        return None

    try:
        apps = [int(a.strip()) for a in raw_apps.split(",")]
    except ValueError:
        apps = [int(a.strip()) for a in raw_apps.split(",") if a.isdigit()]
        logging.info(f"Not all user apps are digits: `{line}`")

    try:
        lat, lon = float(lat), float(lon)
    except ValueError:
        logging.info(f"Invalid geo coords: `{line}`")
        return None  # Возвращаем None, если координаты некорректны

    return AppsInstalled(dev_type, dev_id, lat, lon, apps)


def process_file(args):
    """Process a single file and insert apps installed data into memcached."""
    fn, device_memc, options = args
    processed = errors = 0
    logging.info(f"Processing {fn}")

    with gzip.open(fn, "rt") as fd:  # Используем режим "rt" для чтения как текста
        memc_clients = {}
        if not options.dry:
            for memc_addr in set(device_memc.values()):
                memc_clients[memc_addr] = memcache.Client([memc_addr], socket_timeout=1)

        for line in fd:
            line = line.strip()
            if not line:
                continue

            appsinstalled = parse_appsinstalled(line)
            if not appsinstalled:
                errors += 1
                continue

            memc_addr = device_memc.get(appsinstalled.dev_type)
            if not memc_addr:
                errors += 1
                logging.error(f"Unknown device type: {appsinstalled.dev_type}")
                continue

            ok = insert_appsinstalled(memc_addr, appsinstalled, options.dry, memc_clients=memc_clients)
            if ok:
                processed += 1
            else:
                errors += 1

    if not processed:
        dot_rename(fn)
        return

    err_rate = float(errors) / processed
    if err_rate < NORMAL_ERR_RATE:
        logging.info(f"Acceptable error rate ({err_rate}). Successfully loaded")
    else:
        logging.error(f"High error rate ({err_rate} > {NORMAL_ERR_RATE}). Failed to load {fn}")

    dot_rename(fn)


def main(options):
    """Main function to run the application."""
    device_memc = {
        "idfa": options.idfa,
        "gaid": options.gaid,
        "adid": options.adid,
        "dvid": options.dvid,
    }

    files = glob.glob(options.pattern)
    if not files:
        logging.info("No files to process")
        return

    args = [(fn, device_memc, options) for fn in files]

    with Pool() as pool:
        pool.map(process_file, args)


def prototest():
    """Run a prototype test."""
    sample = "idfa\t1rfw452y52g2gq4g\t55.55\t42.42\t1423,43,567,3,7,23\ngaid\t7rfw452y52g2gq4g\t55.55\t42.42\t7423,424"

    for line in sample.splitlines():
        dev_type, dev_id, lat, lon, raw_apps = line.strip().split("\t")
        apps = [int(a) for a in raw_apps.split(",") if a.isdigit()]
        lat, lon = float(lat), float(lon)
        ua = appsinstalled_pb2.UserApps()
        ua.lat = lat
        ua.lon = lon
        ua.apps.extend(apps)
        packed = ua.SerializeToString()
        unpacked = appsinstalled_pb2.UserApps()
        unpacked.ParseFromString(packed)
        assert ua == unpacked


if __name__ == "__main__":
    op = OptionParser()
    op.add_option("-t", "--test", action="store_true", default=False)
    op.add_option("-l", "--log", action="store", default=None)
    op.add_option("--dry", action="store_true", default=False)
    op.add_option("--pattern", action="store", default="/data/appsinstalled/*.tsv.gz")
    op.add_option("--idfa", action="store", default="127.0.0.1:33013")
    op.add_option("--gaid", action="store", default="127.0.0.1:33014")
    op.add_option("--adid", action="store", default="127.0.0.1:33015")
    op.add_option("--dvid", action="store", default="127.0.0.1:33016")

    (opts, args) = op.parse_args()

    logging.basicConfig(
        filename=opts.log,
        level=logging.INFO if not opts.dry else logging.DEBUG,
        format="[%(asctime)s] %(levelname).1s %(process)d %(message)s",
        datefmt="%Y.%m.%d %H:%M:%S",
    )

    if opts.test:
        prototest()
        sys.exit(0)

    logging.info(f"Memc loader started with options: {opts}")

    try:
        main(opts)
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        sys.exit(1)



