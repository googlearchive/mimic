"""An immutable tree implementation that is backed by the filesystem."""

import datetime
import logging
import os

from . import common

class FilesystemTree(common.Tree):
  """An implementation of Tree backed by the filesystem."""

  """Initializer.

  For safety reasons, only paths beginning with "repos/" are allowed.

  Args:
    repo_path: A subpath beginning with repos/ to consider to be the content of
        the tree.
  """
  def __init__(self, repo_path, namespace='', access_key=None):
    super(FilesystemTree, self).__init__(namespace, access_key)
    assert repo_path.startswith('repos/')
    self.repo_path = repo_path

  def IsMutable(self):
    return False

  def GetFileContents(self, path):
    with open(os.path.join(self.repo_path, path)) as fh:
      return fh.read()

  def GetFileSize(self, path):
    return os.path.getsize(os.path.join(self.repo_path, path))

  def GetFileLastModified(self, path):
    mtime = os.path.getmtime(os.path.join(self.repo_path, path))
    return datetime.datetime.fromtimestamp(mtime)

  def HasFile(self, path):
    return os.path.isfile(os.path.join(self.repo_path, path))

  def HasDirectory(self, path):
    return os.path.isdir(os.path.join(self.repo_path, path))

  def ListDirectory(self, path=None):
    result = []
    path = path or ''
    for (dirname, dnames, fnames) in os.walk(
            os.path.join(self.repo_path, path)):
      result.extend(fnames)
    return result

  def GetFiles(self, path):
    result = []
    for file_path in self.ListDirectory(path):
      result.append((file_path,
                     self.GetFileContents(file_path),
                     self.GetFileLastModified(file_path)))
    return result
