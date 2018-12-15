# Copyright 2018 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Defines a number of module-scope gRPC scenarios to test server shutdown."""

import argparse
import os
import threading
import time
import logging

import grpc

from concurrent import futures
from six.moves import queue

WAIT_TIME = 1000

REQUEST = b'request'
RESPONSE = b'response'

SERVER_RAISES_EXCEPTION = 'server_raises_exception'
SERVER_DEALLOCATED = 'server_deallocated'
SERVER_FORK_CAN_EXIT = 'server_fork_can_exit'

FORK_EXIT = '/test/ForkExit'


class ForkExitHandler(object):

    def unary_unary(self, request, servicer_context):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        return RESPONSE

    def __init__(self):
        self.request_streaming = None
        self.response_streaming = None
        self.request_deserializer = None
        self.response_serializer = None
        self.unary_stream = None
        self.stream_unary = None
        self.stream_stream = None


class GenericHandler(grpc.GenericRpcHandler):

    def service(self, handler_call_details):
        if handler_call_details.method == FORK_EXIT:
            return ForkExitHandler()
        else:
            return None


def run_server(port_queue,):
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=(('grpc.so_reuseport', 0),))
    port = server.add_insecure_port('[::]:0')
    port_queue.put(port)
    server.add_generic_rpc_handlers((GenericHandler(),))
    server.start()
    # threading.Event.wait() does not exhibit the bug identified in
    # https://github.com/grpc/grpc/issues/17093, sleep instead
    time.sleep(WAIT_TIME)


def run_test(args):
    if args.scenario == SERVER_RAISES_EXCEPTION:
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=1),
            options=(('grpc.so_reuseport', 0),))
        server.start()
        raise Exception()
    elif args.scenario == SERVER_DEALLOCATED:
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=1),
            options=(('grpc.so_reuseport', 0),))
        server.start()
        server.__del__()
        while server._state.stage != grpc._server._ServerStage.STOPPED:
            pass
    elif args.scenario == SERVER_FORK_CAN_EXIT:
        port_queue = queue.Queue()
        thread = threading.Thread(target=run_server, args=(port_queue,))
        thread.daemon = True
        thread.start()
        port = port_queue.get()
        channel = grpc.insecure_channel('[::]:%d' % port)
        multi_callable = channel.unary_unary(FORK_EXIT)
        result, call = multi_callable.with_call(REQUEST, wait_for_ready=True)
        os.wait()
    else:
        raise ValueError('unknown test scenario')


if __name__ == '__main__':
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument('scenario', type=str)
    args = parser.parse_args()
    run_test(args)
