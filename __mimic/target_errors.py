"""Class for formatting target environment errors."""

import cgi
from collections import Counter
import logging
import os
import sys
import traceback


_ERROR_HTML_PREAMBLE = """
<html>
<head>
<style>

BODY {
  font-family: sans-serif;
}

H1 {
  font-size: 1.5em;
}

A {
  color: #15c;
  cursor: pointer;
}

.traceback {
  font-family: monospace;
}

.traceback-line {
  margin-left: 1em;
  margin-top: 0.4em;
}

.source {
  color: #a11;
  margin-left: 2em;
  margin-bottom: 0.3em;
}

.path {
  color: #bbb;
}

.path .important {
  color: #000;
  padding-left: 0.1em;
  padding-right: 0.1em;
}

.path .line-number {
  color: #777;
}

.exception-only {
  margin-top: 2em;
  margin-bottom: 2em;
  font-weight: bold;
  white-space: pre;
}

</style>

<script>
// We happily broadcast to any window which embeds us
var TARGET_ORIGIN = '*';
var TARGET_WINDOW = window.opener || window.parent;

function navigate_to(path, line_number) {
  TARGET_WINDOW.postMessage({
      'navigate_to': {
          'path': path,
          'line_number': line_number,
      }
  }, TARGET_ORIGIN);
}
</script>

<head>
<body>
  <h1>500 Uncaught exception</h1>
  <div class="traceback">
"""

_ERROR_HTML_EPILOGUE = """
  </div>
</body>
</html>
"""


def CommonDirectories(paths):
  """Determine common set of directories among a list of directories."""

  candidates = Counter()
  for path in paths:
    parent = os.path.dirname(path)
    candidates[path] += 1
    candidates[parent] += 1

  return [c + '/' for c in candidates if candidates.get(c) > 1]

# Common ancestors of sys.path entries
_SYS_PATH_COMMON_DIRS = CommonDirectories(sys.path)


def _GetLongestPrefix(path):
  match = ''
  for candidate in _SYS_PATH_COMMON_DIRS:
    if path.startswith(candidate) and len(candidate) > len(match):
      match = candidate
  return match


def ExcInfoAsHtml():
  """Format sys.exc_info() as an HTML traceback."""

  def FormatTracebackLine(entry, common_prefix):
    """Format a traceback line."""

    (filename, line_number, function_name, text) = entry
    assert isinstance(line_number, int)
    if not filename.startswith('/'):
      link_html = ("""<a onclick="navigate_to('{}', {})">{}</a>"""
                   .format(cgi.escape(filename, quote=True), line_number,
                           cgi.escape(filename)))
      filename_html = ('<span class="path">'
                       '<span class="important">{}</span>'
                       ' line <span class="line-number">{}</span>'
                       ' in </span>'
                       .format(link_html, line_number))
    else:
      path = filename[len(common_prefix):]
      filename_html = ('<span class="path">{}'
                       '<span class="important">{}</span>'
                       ' line <span class="line-number">{}</span>'
                       ' in </span>'
                       .format(cgi.escape(common_prefix), cgi.escape(path),
                               line_number))
    return ('<div class="traceback-line">{} {}</div>\n'
            '<div class="source">{}</div>\n'
            .format(filename_html, cgi.escape(function_name),
                    cgi.escape(text)))

  exception_type, exception_value, tb = sys.exc_info()
  exception_only = traceback.format_exception_only(exception_type,
                                                   exception_value)
  html = [_ERROR_HTML_PREAMBLE]

  html.append('<div>Traceback (most recent call last):</div>')
  for entry in traceback.extract_tb(tb):
    common_prefix = _GetLongestPrefix(entry[0])
    html.append(format(FormatTracebackLine(entry, common_prefix)))

  html.append('<div class="exception-only">{}</div>'
              .format(cgi.escape(''.join(exception_only))))

  html.append(_ERROR_HTML_EPILOGUE)
  return ''.join(html)


# pylint: disable-msg=unused-argument
def Wsgi500ErrorHandler(request, response, exception):
  """WSGI fallback error handler for HTTP 500 errors."""

  response.clear()
  response.headers['Content-Type'] = 'text/html; charset=utf-8'
  logging.exception(exception)
  response.write(ExcInfoAsHtml())
  response.set_status(500)
