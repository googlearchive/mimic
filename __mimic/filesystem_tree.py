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
    path = os.path.join(self.repo_path, path)
    with open(path) as fh:
      return fh.read()

  def GetFileSize(self, path):
    path = os.path.join(self.repo_path, path)
    return os.path.getsize(path)

  def GetFileLastModified(self, path):
    path = os.path.join(self.repo_path, path)
    mtime = os.path.getmtime(path)
    return datetime.datetime.fromtimestamp(mtime)

  def HasFile(self, path):
    path = os.path.join(self.repo_path, path)
    return os.path.isfile(path)

  def HasDirectory(self, path):
    path = os.path.join(self.repo_path, path)
    return os.path.isdir(path)

  def ListDirectory(self, path=None):
    result = []
    path = path or ''
    path = os.path.join(self.repo_path, path)
    if not os.path.isdir(path):
      raise IOError()
    for (dirname, dnames, fnames) in os.walk(path):
      for fname in fnames:
        full_repo_path = os.path.join(dirname, fname) 

        # Truncate repo_path off the beginning of full_repo_path:
        #   full_repo_path = 'foo/bar/baz'
        #   self.repo_path = 'foo'
        #   item_path = 'bar/baz'
        item_path = full_repo_path[len(self.repo_path) + 1:]

        result.append(item_path)

    return result

  def GetFiles(self, path):
    result = []
    for file_path in self.ListDirectory(path):
      result.append((file_path,
                     self.GetFileContents(file_path),
                     self.GetFileLastModified(file_path)))
    return result
