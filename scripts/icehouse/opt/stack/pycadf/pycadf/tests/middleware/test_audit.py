# Copyright (c) 2014 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

import mock
import webob

from pycadf.audit import api as cadf_api
from pycadf.middleware import audit
from pycadf.tests import base


class FakeApp(object):
    def __call__(self, env, start_response):
        body = 'Some response'
        start_response('200 OK', [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(sum(map(len, body))))
        ])
        return [body]


class FakeFailingApp(object):
    def __call__(self, env, start_response):
        raise Exception("It happens!")


@mock.patch('oslo.messaging.get_transport', mock.MagicMock())
class AuditMiddlewareTest(base.TestCase):
    ENV_HEADERS = {'HTTP_X_SERVICE_CATALOG':
                   '''[{"endpoints_links": [],
                        "endpoints": [{"adminURL":
                                       "http://host:8774/v2/admin",
                                       "region": "RegionOne",
                                       "publicURL":
                                       "http://host:8774/v2/public",
                                       "internalURL":
                                       "http://host:8774/v2/internal",
                                       "id": "resource_id"}],
                        "type": "compute",
                        "name": "nova"},]''',
                   'HTTP_X_USER_ID': 'user_id',
                   'HTTP_X_USER_NAME': 'user_name',
                   'HTTP_X_AUTH_TOKEN': 'token',
                   'HTTP_X_PROJECT_ID': 'tenant_id',
                   'HTTP_X_IDENTITY_STATUS': 'Confirmed'}

    def setUp(self):
        super(AuditMiddlewareTest, self).setUp()
        self.map_file = 'etc/pycadf/nova_api_audit_map.conf'

    def test_api_request(self):
        middleware = audit.AuditMiddleware(
            FakeApp(),
            audit_map_file='etc/pycadf/nova_api_audit_map.conf',
            service_name='pycadf')
        self.ENV_HEADERS['REQUEST_METHOD'] = 'GET'
        req = webob.Request.blank('/foo/bar',
                                  environ=self.ENV_HEADERS)
        with mock.patch('oslo.messaging.Notifier.info') as notify:
            middleware(req)
            # Check first notification with only 'request'
            call_args = notify.call_args_list[0][0]
            self.assertEqual(call_args[1], 'http.request')
            self.assertEqual(set(call_args[2].keys()),
                             set(['request']))

            request = call_args[2]['request']
            self.assertEqual(request['PATH_INFO'], '/foo/bar')
            self.assertEqual(request['REQUEST_METHOD'], 'GET')
            self.assertIn('CADF_EVENT', request)
            self.assertEqual(request['CADF_EVENT']['outcome'], 'pending')

            # Check second notification with request + response
            call_args = notify.call_args_list[1][0]
            self.assertEqual(call_args[1], 'http.response')
            self.assertEqual(set(call_args[2].keys()),
                             set(['request', 'response']))

            request = call_args[2]['request']
            self.assertEqual(request['PATH_INFO'], '/foo/bar')
            self.assertEqual(request['REQUEST_METHOD'], 'GET')
            self.assertIn('CADF_EVENT', request)
            self.assertEqual(request['CADF_EVENT']['outcome'], 'success')

    def test_api_request_failure(self):
        middleware = audit.AuditMiddleware(
            FakeFailingApp(),
            audit_map_file='etc/pycadf/nova_api_audit_map.conf',
            service_name='pycadf')
        self.ENV_HEADERS['REQUEST_METHOD'] = 'GET'
        req = webob.Request.blank('/foo/bar',
                                  environ=self.ENV_HEADERS)
        with mock.patch('oslo.messaging.Notifier.info') as notify:
            try:
                middleware(req)
                self.fail("Application exception has not been re-raised")
            except Exception:
                pass
            # Check first notification with only 'request'
            call_args = notify.call_args_list[0][0]
            self.assertEqual(call_args[1], 'http.request')
            self.assertEqual(set(call_args[2].keys()),
                             set(['request']))

            request = call_args[2]['request']
            self.assertEqual(request['PATH_INFO'], '/foo/bar')
            self.assertEqual(request['REQUEST_METHOD'], 'GET')
            self.assertIn('CADF_EVENT', request)
            self.assertEqual(request['CADF_EVENT']['outcome'], 'pending')

            # Check second notification with request + response
            call_args = notify.call_args_list[1][0]
            self.assertEqual(call_args[1], 'http.response')
            self.assertEqual(set(call_args[2].keys()),
                             set(['request', 'exception']))

            request = call_args[2]['request']
            self.assertEqual(request['PATH_INFO'], '/foo/bar')
            self.assertEqual(request['REQUEST_METHOD'], 'GET')
            self.assertIn('CADF_EVENT', request)
            self.assertEqual(request['CADF_EVENT']['outcome'], 'unknown')

    def test_process_request_fail(self):
        def func_error(self, req):
            raise Exception('error')
        self.stubs.Set(cadf_api.OpenStackAuditApi, 'append_audit_event',
                       func_error)
        middleware = audit.AuditMiddleware(
            FakeApp(),
            audit_map_file='etc/pycadf/nova_api_audit_map.conf',
            service_name='pycadf')
        req = webob.Request.blank('/foo/bar',
                                  environ={'REQUEST_METHOD': 'GET'})
        middleware.process_request(req)

    def test_process_response_fail(self):
        def func_error(self, req, res):
            raise Exception('error')
        self.stubs.Set(cadf_api.OpenStackAuditApi, 'mod_audit_event',
                       func_error)
        middleware = audit.AuditMiddleware(
            FakeApp(),
            audit_map_file='etc/pycadf/nova_api_audit_map.conf',
            service_name='pycadf')
        req = webob.Request.blank('/foo/bar',
                                  environ={'REQUEST_METHOD': 'GET'})
        middleware.process_response(req, webob.response.Response())
