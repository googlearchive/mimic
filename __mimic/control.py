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

"""A simple web application to control Mimic."""


import cgi
import cStringIO
import httplib
import json
import logging
import os
import re
import zipfile

from . import common
from . import composite_query
from . import filesystem_tree

from google.appengine.api import channel
from google.appengine.ext import webapp


_MAX_LOG_MESSAGE = 1024  # will keep the channel message under the 32K Limit

class _TreeHandler(webapp.RequestHandler):
  """Base class for RequestHandlers that require a Tree object."""

  def __init__(self, request, response):
    """Initializes this request handler with the given Request and Response."""
    webapp.RequestHandler.initialize(self, request, response)
    self._tree = self.app.config.get('tree')

  def _HandleCorsResponse(self):
    """Take care of CORS reponses."""
    origin = self.request.headers.get('Origin')
    # If not a CORS request, do nothing
    if not origin:
      return

    if origin not in common.config.CORS_ALLOWED_ORIGINS:
      self.response.set_status(httplib.UNAUTHORIZED)
      self.response.headers['Content-Type'] = 'text/plain; charset=utf-8'
      self.response.write('Disallowed origin {}'.format(origin))
      return
    # OK, CORS access allowed
    self.response.headers['Access-Control-Allow-Origin'] = origin
    self.response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT'
    self.response.headers['Access-Control-Max-Age'] = '600'
    allowed_headers = common.config.CORS_ALLOWED_HEADERS
    self.response.headers['Access-Control-Allow-Headers'] = allowed_headers
    self.response.headers['Access-Control-Allow-Credentials'] = 'true'

  def dispatch(self):  # pylint: disable-msg=g-bad-name,missing-docstring
    if (common.config.ALLOWED_USER_CONTENT_HOSTS and
        self.request.host not in common.config.ALLOWED_USER_CONTENT_HOSTS):
      self.response.set_status(httplib.FORBIDDEN)
      self.response.headers['Content-Type'] = 'text/plain; charset=utf-8'
      self.response.write('User content forbidden on HTTP host {}'
                          .format(self.request.host))
      return
    # explicit mixed case 'Content-Type' for dev_appserver tests
    self.response.headers['Content-Type'] = 'text/html; charset=utf-8'
    self._HandleCorsResponse()
    super(_TreeHandler, self).dispatch()

  def options(self):  # pylint: disable-msg=g-bad-name
    """Handle OPTIONS requests."""
    # allow CORS requests
    pass


class _ClearHandler(_TreeHandler):
  """Handler for clearing all files."""

  def post(self):  # pylint: disable-msg=C6409
    """Clear all files."""
    if self._tree.IsMutable():
      self._tree.Clear()
    else:
      self.error(httplib.BAD_REQUEST)


class _DeleteHandler(_TreeHandler):
  """Handler for delete files/directories."""

  def post(self):  # pylint: disable-msg=C6409
    """Delete all files under the specified path."""
    path = self.request.get('path')
    if not path or not self._tree.IsMutable():
      self.error(httplib.BAD_REQUEST)
      return
    self._tree.DeletePath(path)


class _DirHandler(_TreeHandler):
  """Handler for enumerating files."""

  def get(self):  # pylint: disable-msg=C6409
    """Retrieve list of files under the specified path."""
    path = self.request.get('path', None)
    paths = self._tree.ListDirectory(path)
    files = [{'path': path, 'mime_type': common.GuessMimeType(path)}
             for path in paths]
    self.response.headers['Content-Type'] = 'application/json'
    self.response.out.write(common.config.JSON_ENCODER.encode(files))


def prepare_zip_response_from_tree(
    response, tree, filename, use_basepath=False):
  paths = tree.ListDirectory(None)
  buf = cStringIO.StringIO()
  zf = zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED)

  basepath = ''
  if use_basepath:
    basepath = re.sub(r'\.zip$', '', filename) + '/'
    if basepath.startswith('repos/'):
      basepath = basepath[len('repos/'):]

  for path in paths:
    if path.endswith('.playground'):
      continue

    last_modified = tree.GetFileLastModified(path)
    zi = zipfile.ZipInfo(basepath + path,
                         last_modified.timetuple()[:6])
    zi.external_attr = 0640 << 16L # -rw-r-----
    zf.writestr(zi, tree.GetFileContents(path))
  zf.close()
  content_disposition = 'attachment; filename="{}"'.format(filename)

  response.headers['Content-Disposition'] = content_disposition
  response.headers['Content-Type'] = 'application/zip'
  response.write(buf.getvalue())


class _ZipHandler(_TreeHandler):
  """Handler for downloading files as ZIP archive."""

  def get(self):  # pylint: disable-msg=C6409
    """Download the Zip archive."""

    requested_filename = self.request.get('filename')
    safe_requested_filename = None
    if requested_filename:
      # Sanitize the filename, since it is used in the response.
      # (An Inquisition scan noticed this.)
      safe_requested_filename = re.sub(r'[^a-zA-Z0-9\.\-_]', '_',
                                       requested_filename)

    filename = (safe_requested_filename or
                '{}.zip'.format(self.app.config['namespace']))
    prepare_zip_response_from_tree(
      self.response, self._tree, filename,
      use_basepath=self.request.get('use_basepath') != 'false')


class _ZipFromRepoHandler(webapp.RequestHandler):
  """Request handler for serving zips of repos without a project."""

  def get(self):  # pylint: disable-msg=C6409
    """Download a repo as a Zip archive."""
    tree = filesystem_tree.FilesystemTree(repo_path=self.request.get('repo'))
    filename = (self.request.get('filename') or
                re.sub(r'\W', '_', self.request.get('repo')))
    try:
      prepare_zip_response_from_tree(
        self.response, tree, filename, use_basepath=True)
    except IOError:
      self.response.write('No such repo')
      self.response.set_status(404)


class _FileHandler(_TreeHandler):
  """Handler for getting/setting files."""

  def get(self):  # pylint: disable-msg=C6409
    """Get a file's contents."""
    self.response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    path = self.request.get('path')
    if not path:
      self.error(httplib.BAD_REQUEST)
      self.response.write('Path must be specified')
      return
    data = self._tree.GetFileContents(path)
    if data is None:
      self.error(httplib.NOT_FOUND)

      # Technically the error message is not served as HTML so we
      # don't need to escape the parameter. But this showed up in an
      # Inquisition scan so I'm fixing it.
      safe_path = cgi.escape(path)

      self.response.write('File does not exist: %s' % safe_path)
      return
    last_modified = self._tree.GetFileLastModified(path)
    last_modified_str = last_modified.strftime(common.RFC_1123_DATE_FORMAT)
    self.response.headers['Content-Type'] = common.GuessMimeType(path)
    self.response.headers['X-Content-Type-Options'] = 'nosniff'
    self.response.headers['Last-Modified'] = last_modified_str
    self.response.out.write(data)

  def put(self):  # pylint: disable-msg=C6409
    """Set a file's contents."""
    path = self.request.get('path')
    if not path or not self._tree.IsMutable():
      self.error(httplib.BAD_REQUEST)
      return
    self._tree.SetFile(path, self.request.body)
    file_data = {'path': path, 'mime_type': common.GuessMimeType(path)}
    self.response.headers['Content-Type'] = 'application/json'
    self.response.out.write(common.config.JSON_ENCODER.encode(file_data))


class _MoveHandler(_TreeHandler):
  """Handler for moving files."""

  def post(self):  # pylint: disable-msg=C6409
    """Rename file with the specified path."""
    path = self.request.get('path')
    newpath = self.request.get('newpath')
    if not path or not self._tree.IsMutable():
      self.error(httplib.BAD_REQUEST)
      return
    if not newpath or newpath == path:
      self.error(httplib.BAD_REQUEST)
      return
    self._tree.MoveFile(path, newpath)


class _IndexHandler(webapp.RequestHandler):
  """Handler for getting index.yaml definitions.

  GET: returns the auto-generated index.yaml contents.
  POST: clears the auto-generated index.yaml contents.
  """

  def get(self):  # pylint: disable-msg=C6409
    self.response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    # TODO: composite_query._RecordIndex() records the app's index
    # yaml in the munged (ie, project-name-prefixed) namespace, so _IndexHandler
    # must read from that namespace. Likely the right thing to do here is to
    # separate the datastore patches into their own unit that can be installed
    # separately from the target_env, rather than manaully prefix the namespace
    # here.
    self.response.out.write(composite_query.GetIndexYaml())

  def post(self):  # pylint: disable-msg=C6409
    # clear and then return the cleared index spec
    composite_query.ClearIndexYaml()
    self.get()


class _LogRequestHandler(webapp.RequestHandler):
  """Handler for real time logging."""

  def __init__(self, request, response):
    """Initializes this request handler with the given Request and Response."""
    super(_LogRequestHandler, self).__init__(request, response)
    webapp.RequestHandler.initialize(self, request, response)
    self._create_channel_fn = self.app.config.get('create_channel_fn')

  def get(self):  # pylint: disable-msg=C6409, C6111
    parent = os.path.dirname(__file__)
    path = os.path.join(parent, 'templates', 'log.html')
    with open(path) as f:
      data = f.read()
    token = self._create_channel_fn(self.app.config['namespace'])
    values = {
        'token': token,
    }
    # TODO: It would probably be safer to use real templating instead
    # of string interpolation, but that would require additional code to
    # separate mimic and the client's use of the template cache.
    self.response.out.write(data % values)


# TODO: It may be better to collect all log records during script
# execution and only send them back after the script is complete.  Multiple
# log records could be bundled together for efficiency, and there would be no
# concern over nested logging calls.  The disadvantage is that this sort of
# mechanism would be useless in debugging scripts that take too long to
# execute since the entire script would have timed out before there was any
# chance to send the log records back.


class LoggingHandler(logging.Handler):
  """A logging.LogHandler that sends log messages over a channel."""

  def __init__(self, namespace, send_message_fn=channel.send_message):
    logging.Handler.__init__(self)
    self.namespace = namespace
    self._send_message_fn = send_message_fn
    self._sending = False  # prevent recursive logging

  def emit(self, record):
    """Emit a log message (see documentation for the logging module)."""
    if self._sending:
      # we don't want logging calls from within emit() to trigger another
      # log message, so ignore any nested logging calls
      return

    self._sending = True
    values = {
        'created': record.created,
        'levelname': record.levelname,
        'message': record.getMessage()[:_MAX_LOG_MESSAGE],
    }
    encoded = json.dumps(values)
    self._send_message_fn(self.namespace, encoded)
    self._sending = False


class _VersionIdHandler(webapp.RequestHandler):
  """Handler that returns the version ID of this mimic."""

  def get(self):  # pylint: disable-msg=C6409, C6111
    self.response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    self.response.headers['Access-Control-Allow-Origin'] = '*'
    self.response.out.write('MIMIC\n')
    self.response.out.write('version_id=%s\n' % str(common.VERSION_ID))


def ControlRequestRequiresNamespace(path_info):
  """Determines if the control request (by path_info) requires a namespace."""
  for handler_path in common.CONTROL_PATHS_REQUIRING_NAMESPACE:
    if path_info.startswith(handler_path):
      return True
  return False


def ControlRequestRequiresTree(path_info):
  """Determines if the control request (by path_info) requires a Tree."""
  for handler_path in common.CONTROL_PATHS_REQUIRING_TREE:
    if path_info.startswith(handler_path):
      return True
  return False


# TODO: protect against XSRF
def MakeControlApp(tree, namespace, create_channel_fn=channel.create_channel):
  """Create and return a WSGI application for controlling Mimic."""
  # standard handlers
  handlers = [
      ('/clear', _ClearHandler),
      ('/delete', _DeleteHandler),
      ('/dir', _DirHandler),
      ('/ziprepo', _ZipFromRepoHandler),
      ('/zip', _ZipHandler),
      ('/file', _FileHandler),
      ('/index', _IndexHandler),
      ('/log', _LogRequestHandler),
      ('/move', _MoveHandler),
      ('/version_id', _VersionIdHandler),
  ]
  # prepend CONTROL_PREFIX to all handler paths
  handlers = [(common.CONTROL_PREFIX + p, h) for (p, h) in handlers]
  config = {'tree': tree, 'namespace': namespace,
            'create_channel_fn': create_channel_fn}
  return webapp.WSGIApplication(handlers, debug=True, config=config)
