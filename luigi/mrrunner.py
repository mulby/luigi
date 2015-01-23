#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2012 Spotify AB
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

"""The hadoop runner.

This module contains the main() method which will be used to run the
mapper and reducer on the Hadoop nodes.
"""

from contextlib import contextmanager
import errno
import functools
import os
import sys
import tarfile
import cPickle as pickle
import logging
import traceback


def profile_if_enabled(func):

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        profiler = os.getenv('luigi_runner_profiler')
        if profiler:
            attempt_id = os.getenv('mapred_task_id', os.getenv('mapreduce_task_attempt_id', os.getpid()))
            job_id = os.getenv('mapred_job_id', os.getenv('mapreduce_job_id', 'unknown_job'))
            base_path = os.getenv('luigi_runner_profiler_path', '/mnt/tmp/luigi/mrrunner/profiling')
            profile_capture_path = os.path.join(base_path, job_id, attempt_id + '.' + profiler + '.trace')
            try:
                os.makedirs(os.path.dirname(profile_capture_path))
            except OSError as exception:
                if exception.errno != errno.EEXIST:
                    profiler = None

        if not profiler:
            return func(*args, **kwargs)

        profiler = profiler.lower()
        if profiler == 'cprofile':
            from cProfile import Profile
            prof = Profile()
            result = prof.runcall(func, *args, **kwargs)
            prof.dump_stats(profile_capture_path)
            return result
        elif profiler == 'pyinstrument':
            with pyinstrument_profiling_enabled(profile_capture_path):
                return func(*args, **kwargs)

    return wrapper


@contextmanager
def pyinstrument_profiling_enabled(profile_capture_path):
    try:
        from pyinstrument import Profiler
    except ImportError:
        yield
        return

    profiler = Profiler(use_signal=False)
    profiler.start()
    try:
        yield
    finally:
        profiler.stop()
        profiler.save(filename=profile_capture_path)


class Runner(object):
    """Run the mapper or reducer on hadoop nodes."""

    def __init__(self, job=None):
        self.extract_packages_archive()
        self.job = job or pickle.load(open("job-instance.pickle"))
        self.job._setup_remote()

    @profile_if_enabled
    def run(self, kind, stdin=sys.stdin, stdout=sys.stdout):
        if kind == "map":
            self.job._run_mapper(stdin, stdout)
        elif kind == "combiner":
            self.job._run_combiner(stdin, stdout)
        elif kind == "reduce":
            self.job._run_reducer(stdin, stdout)
        else:
            raise Exception('weird command: %s' % kind)

    def extract_packages_archive(self):
        if not os.path.exists("packages.tar"):
            return

        tar = tarfile.open("packages.tar")
        for tarinfo in tar:
            tar.extract(tarinfo)
        tar.close()
        if '' not in sys.path:
            sys.path.insert(0, '')


def print_exception(exc):
    tb = traceback.format_exc(exc)
    print >> sys.stderr, 'luigi-exc-hex=%s' % tb.encode('hex')


def main(args=sys.argv, stdin=sys.stdin, stdout=sys.stdout, print_exception=print_exception):
    """Run either the mapper or the reducer from the class instance in the file "job-instance.pickle".

    Arguments:

    kind -- is either map or reduce
    """
    try:
        # Set up logging.
        logging.basicConfig(level=logging.WARN)

        kind = args[1]
        Runner().run(kind, stdin=stdin, stdout=stdout)
    except Exception, exc:
        # Dump encoded data that we will try to fetch using mechanize
        print_exception(exc)
        raise

if __name__ == '__main__':
    main()
