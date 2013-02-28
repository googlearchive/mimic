#!/usr/bin/env python
#
# Copyright 2012 Google Inc. All Rights Reserved.
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

"""Unit tests for control.py."""

import cStringIO
import httplib
import json
import logging
import re
import time
import urllib


# Import test_util first, to ensure python27 / webapp2 are setup correctly
from tests import test_util

from __mimic import common  # pylint: disable-msg=C6203
from __mimic import composite_query
from __mimic import control
from __mimic import datastore_tree

import unittest


_VERSION_STRING_FORMAT = """\
MIMIC
version_id=%s
"""


def _CreateFakeChannel(client_id):
  return 'token:%s' % client_id


class ControlAppTest(unittest.TestCase):
  """Test the app created by MakeControlApp."""

  def setUp(self, tree=None):
    test_util.InitAppHostingApi()
    self.setUpApplication(tree)
    # these are updated after StartResponse is called
    self._status = None
    self._headers = None
    self._output = ''

  def setUpApplication(self, tree=None):
    """Sets up the control application and its tree."""
    if tree:
      self._tree = tree
    else:
      self._tree = datastore_tree.DatastoreTree()
    self._application = control.MakeControlApp(
        self._tree, create_channel_fn=_CreateFakeChannel)

  def StartResponse(self, status, headers):
    """A WSGI start_response method."""
    self._status = status
    self._headers = dict(headers)
    self._output = ''
    return self.AccumulateOutput

  def AccumulateOutput(self, data):
    """Used by StartResponse to accumlate response data."""
    self._output += data

  def RunWSGI(self, path_query, headers=[], method='GET', data=None,
              form=False):
    """Invoke the application on a given path/query.

    Args:
      path_query: The path and optional query portion of the URL, for example
          /foo or /foo?x=123
      headers: The HTTP request headers to be sent.
      method: The HTTP method, such as GET, POST, OPTIONS, PUT, DELETE
      data: Optional data to be sent as the body of a POST or PUT
      form: True indicates application/x-www-form-urlencoded should be used
          as the content type, otherwise the default of test/plain is used.
    """
    env = test_util.GetDefaultEnvironment()
    # setup path and query
    if '?' in path_query:
      path, query = path_query.split('?', 1)
      env['PATH_INFO'] = path
      env['QUERY_STRING'] = query
    else:
      env['PATH_INFO'] = path_query
    # HTTP request headers
    if headers:
      for k, v in headers.items():
        env['HTTP_' + k.upper().replace('-', '_')] = v
    # handle request data
    if data is not None:
      input_stream = cStringIO.StringIO(data)
      if form:
        env['CONTENT_TYPE'] = 'application/x-www-form-urlencoded'
      else:
        env['CONTENT_TYPE'] = 'text/plain; charset=utf-8'
      env['CONTENT_LENGTH'] = len(data)
      env['wsgi.input'] = input_stream
    env['REQUEST_METHOD'] = method
    # invoke the application
    response = self._application(env, self.StartResponse)
    for data in response:
      self.AccumulateOutput(data)

  def Check(self, status_code, headers=None, output=None):
    """Check the results of invoking the application.

    Args:
      status_code: The expected numeric HTTP status code.
      headers: The expected HTTP headers. A dict.
      output: The expected output, or None if output should not be checked.
    """
    actual = int(self._status.split(' ', 1)[0])
    self.assertEquals(status_code, actual)
    if output is not None:
      self.assertEquals(output, self._output)
    if headers is not None:
      self.assertEquals(headers, self._headers)

  def testGetFileContents(self):
    self._tree.SetFile('foo.html', '123')
    self.RunWSGI('/_ah/mimic/file?path=foo.html')
    headers = {
        'Content-Length': '3',
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff',
    }
    self.Check(httplib.OK, headers=headers, output='123')

  def testGetFileContentsAlternateContentType(self):
    self._tree.SetFile('foo.css', 'pretty')
    self.RunWSGI('/_ah/mimic/file?path=foo.css')
    headers = {
        'Content-Length': '6',
        'Content-Type': 'text/css; charset=utf-8',
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff',
    }
    self.Check(httplib.OK, headers=headers, output='pretty')

  def testCorsPreflightAllowed(self):
    self.RunWSGI('/_ah/mimic/file?path=foo.txt', method='OPTIONS',
                 headers={'Origin': 'http://localhost:8080'})
    headers = {
        'Access-Control-Allow-Credentials': 'true',
        'Access-Control-Allow-Headers': 'Origin, Accept',
        'Access-Control-Allow-Methods': 'GET, POST, PUT',
        'Access-Control-Allow-Origin': 'http://localhost:8080',
        'Access-Control-Max-Age': '600',
        'Content-Length': '0',
        # App Engine's default MIME type
        'content-type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-cache',
    }
    self.Check(httplib.OK, headers=headers)

  def testCorsPreflightDenied(self):
    self.RunWSGI('/_ah/mimic/file?path=foo.txt', method='OPTIONS',
                 headers={'Origin': 'http://otherdomain.com'})
    headers = {
        'Content-Length': '42',
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-cache',
    }
    self.Check(httplib.UNAUTHORIZED, headers=headers)

  def testCorsAllowHeaders(self):
    self.RunWSGI('/_ah/mimic/file?path=foo.txt', method='OPTIONS',
                 headers={'Origin': 'http://localhost:8080'})
    self.Check(httplib.OK)
    self.assertEquals('Origin, Accept',
                      self._headers.get('Access-Control-Allow-Headers'))
    # allow custom 'X-Foo' HTTP request header
    saved_headers = common.config.CORS_ALLOWED_HEADERS
    common.config.CORS_ALLOWED_HEADERS = 'Origin, Accept, X-Foo'
    try:
      self.RunWSGI('/_ah/mimic/file?path=foo.txt', method='OPTIONS',
                   headers={'Origin': 'http://localhost:8080', 'X-Foo': 'Bar'})
    finally:
      common.config.CORS_ALLOWED_HEADERS = saved_headers
    self.Check(httplib.OK)
    self.assertEquals('Origin, Accept, X-Foo',
                      self._headers.get('Access-Control-Allow-Headers'))

  def testGetFileNotFound(self):
    self.RunWSGI('/_ah/mimic/file?path=foo.html')
    headers = {
        'Content-Length': '29',
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-cache',
    }
    self.Check(httplib.NOT_FOUND, headers=headers,
               output='File does not exist: foo.html')

  def testGetFileBadRequest(self):
    self.RunWSGI('/_ah/mimic/file')
    headers = {
        'Content-Length': '22',
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-cache',
    }
    self.Check(httplib.BAD_REQUEST, headers=headers,
               output='Path must be specified')

  def testDeletePath(self):
    class MutableTree(object):
      def DeletePath(self, path):
        self.path = path

      def IsMutable(self):
        return True

    self.setUpApplication(MutableTree())
    self.RunWSGI('/_ah/mimic/delete?path=foo.html', method='POST', data='')
    self.Check(httplib.OK)
    self.assertEqual(self._tree.path, 'foo.html')

  def testDeletePathBadRequest(self):
    self.RunWSGI('/_ah/mimic/delete', method='POST', data='123')
    self.Check(httplib.BAD_REQUEST)

  def testDeletePathImmutable(self):
    class ImmutableTree(object):
      def IsMutable(self):
        return False

    self.setUpApplication(ImmutableTree())
    self.RunWSGI('/_ah/mimic/delete?path=foo.html', method='POST', data='')
    self.Check(httplib.BAD_REQUEST)

  def testSetFile(self):
    class MutableTree(object):
      def SetFile(self, path, contents):
        self.path = path
        self.contents = contents

      def IsMutable(self):
        return True

    self.setUpApplication(MutableTree())
    self.RunWSGI('/_ah/mimic/file?path=foo.html', method='PUT', data='abc')
    self.Check(httplib.OK)
    self.assertEqual(self._tree.contents, 'abc')
    self.assertEqual(self._tree.path, 'foo.html')

  def testSetFileBadRequest(self):
    self.RunWSGI('/_ah/mimic/file', method='PUT', data='123')
    self.Check(httplib.BAD_REQUEST)

  def testSetFileImmutable(self):
    class ImmutableTree(object):
      def IsMutable(self):
        return False

    self.setUpApplication(ImmutableTree())
    self.RunWSGI('/_ah/mimic/file?path=foo.html', method='PUT', data='abc')
    self.Check(httplib.BAD_REQUEST)

  def testMoveFile(self):
    class MutableTree(object):
      def MoveFile(self, path, newpath):
        self.path = path
        self.newpath = newpath

      def IsMutable(self):
        return True

    self.setUpApplication(MutableTree())
    self.RunWSGI('/_ah/mimic/move?path=foo.html&newpath=bar.txt',
                 method='POST', data='')
    self.Check(httplib.OK)
    self.assertEqual(self._tree.path, 'foo.html')
    self.assertEqual(self._tree.newpath, 'bar.txt')

  def testMoveFileBadRequest(self):
    self.RunWSGI('/_ah/mimic/move', method='POST', data='')
    self.Check(httplib.BAD_REQUEST)

  def testMoveFileSamePathBadRequest(self):
    self.RunWSGI('/_ah/mimic/move?path=foo.html&newpath=foo.html',
                 method='POST', data='')
    self.Check(httplib.BAD_REQUEST)

  def testMoveFileImmutable(self):
    class ImmutableTree(object):
      def IsMutable(self):
        return False

    self.setUpApplication(ImmutableTree())
    self.RunWSGI('/_ah/mimic/move?path=foo.html&newpath=bar.txt',
                 method='POST', data='')
    self.Check(httplib.BAD_REQUEST)

  def testClear(self):
    self.RunWSGI('/_ah/mimic/clear', method='POST', data='')
    self.Check(httplib.OK)
    self.assertEquals([], self._tree.ListDirectory('/'))

  def testClearImmutable(self):
    class ImmutableTree(object):
      def IsMutable(self):
        return False

    self.setUpApplication(ImmutableTree())
    self.RunWSGI('/_ah/mimic/clear', method='POST', data='')
    self.Check(httplib.BAD_REQUEST)

  def testLog(self):
    self.RunWSGI('/_ah/mimic/log')
    self.Check(httplib.OK)
    # output should have the logging token in it
    self.assertIn('"token:logging"', self._output)

  def testIndex(self):
    composite_query._RecordIndex('foo')
    composite_query._RecordIndex('bar')
    self.RunWSGI('/_ah/mimic/index')
    self.Check(httplib.OK, output="""indexes:

bar

foo""")
    self.RunWSGI('/_ah/mimic/index', method='POST', data='')
    self.Check(httplib.OK, output="""indexes:

""")

  def testGetVersionId(self):
    self.RunWSGI('/_ah/mimic/version_id')
    self.Check(httplib.OK)
    expected = _VERSION_STRING_FORMAT % common.VERSION_ID
    self.assertEquals(expected, self._output)

  def testControlRequestRequiresTree(self):
    self.assertTrue(control.ControlRequestRequiresTree('/_ah/mimic/file'))
    self.assertTrue(control.ControlRequestRequiresTree('/_ah/mimic/clear'))
    self.assertFalse(control.ControlRequestRequiresTree('/user/file'))
    self.assertFalse(control.ControlRequestRequiresTree('/user/clear'))
    self.assertFalse(control.ControlRequestRequiresTree('/file'))


class LoggingHandlerTest(unittest.TestCase):
  def setUp(self):
    self._values = None
    self._handler = control.LoggingHandler(send_message_fn=self._SendMessage)

  def _SendMessage(self, client_id, message):
    # check the client_id, decode and save the message
    self.assertEquals(client_id, control._LOGGING_CLIENT_ID)
    self.assertIsNone(self._values)
    self._values = json.loads(message)

  def testNormal(self):
    before = time.time()
    record = logging.LogRecord('', logging.INFO, 'foo.py', 123, 'my message',
                               (), None)
    after = time.time()
    self._handler.handle(record)
    self.assertEquals('INFO', self._values['levelname'])
    self.assertEquals('my message', self._values['message'])
    created = self._values['created']
    self.assertTrue(before <= created and created <= after)

  def testLongMessage(self):
    message = 'this is a start' + ('1234567890' * 1000)
    self.assertTrue(len(message) > control._MAX_LOG_MESSAGE)
    record = logging.LogRecord('', logging.INFO, 'foo.py', 123, message,
                               (), None)
    self._handler.handle(record)
    expected = message[:control._MAX_LOG_MESSAGE]  # should be truncated
    self.assertEquals(expected, self._values['message'])


if __name__ == '__main__':
  unittest.main()
