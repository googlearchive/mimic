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

"""A mutable tree implementation that is backed by Datastore."""




from . import common

from google.appengine.ext import ndb

# The total entity size is 1048572 (1MB - 4), and having some margin below it.
MAX_BYTES_FOR_ENTITY = 921600  # 900 kbytes


def _SplitByLength(seq, length):
  """A helper function for spliting a string or blob into sized chunks."""
  return [seq[i:i+length] for i in range(0, len(seq), length)]


# TODO: Unfortunately this model will pollute the target application's
# Datastore.  The name (prefixed with _Ah) was chosen to minimize collision,
# but there may be a better mechanism.
class _AhMimicFile(ndb.Model):
  """A Model to store file contents in Datastore.

  The file's path should be used as the key for the entity.
  """
  contents = ndb.BlobProperty()
  chunk_keys = ndb.KeyProperty(repeated=True, indexed=False)
  updated = ndb.DateTimeProperty(auto_now=True, indexed=False)

  def GetContents(self):
    if self.chunk_keys:
      chunk_list = ndb.get_multi(self.chunk_keys)
      contents_list = [chunk.contents for chunk in chunk_list]
      return ''.join(contents_list)
    else:
      return self.contents


class _AhMimicChunk(ndb.Model):
  """A Model to store a chunk of file contents.

  All of the siblings should have one single _AhMimicFile entity as a parent.
  """
  contents = ndb.BlobProperty()


class DatastoreTree(common.Tree):
  """An implementation of Tree backed by Datastore."""

  # pylint:disable-msg=unused-argument
  def __init__(self, namespace='', access_key=None):
    super(DatastoreTree, self).__init__(namespace)
    # Having a root entity key allows us to use ancestor queries for strong
    # consistency in the High Replication Datastore
    assert namespace is not None
    self.root = ndb.Key(_AhMimicFile, '/',
                        namespace=namespace or common.config.NAMESPACE)

  def __repr__(self):
    return '<{0} root={1}>'.format(self.__class__.__name__, self.root)

  def IsMutable(self):
    return True

  def GetFileContents(self, path):
    entity = _AhMimicFile.get_by_id(path, parent=self.root)
    if entity is None:
      return None
    return entity.GetContents()

  def GetFileSize(self, path):
    contents = self.GetFileContents(path)
    if contents is None:
      return None
    return len(contents)

  def GetFileLastModified(self, path):
    entity = _AhMimicFile.get_by_id(path, parent=self.root)
    if entity is None:
      return None
    return entity.updated

  def HasFile(self, path):
    # root always exists, even if there are no files in the datastore
    if path == '':  # pylint: disable-msg=C6403
      return True
    entity = _AhMimicFile.get_by_id(path, parent=self.root)
    return entity is not None

  @ndb.transactional(xg=True)
  def MoveFile(self, path, newpath):
    entity = _AhMimicFile.get_by_id(path, parent=self.root)
    if entity is None:
      return False
    self.SetFile(newpath, entity.GetContents())
    keys_to_delete = [entity.key]
    if entity.chunk_keys:
      keys_to_delete.extend(entity.chunk_keys)
    ndb.delete_multi(keys_to_delete)
    return True

  def DeletePath(self, path):
    """Delete files with specified leading path."""
    normpath = self._NormalizeDirectoryPath(path)
    keys = ndb.Query(ancestor=self.root).fetch(keys_only=True)
    keys = [k for k in keys if
            k.id() == path or
            (k.string_id() and k.string_id().startswith(normpath)) or
            k.parent().id() == path or
            k.parent().id().startswith(normpath)]
    if not keys:
      return False
    ndb.delete_multi(keys)
    return True

  def Clear(self):
    keys = ndb.Query(ancestor=self.root).fetch(keys_only=True)
    ndb.delete_multi(keys)

  @ndb.transactional
  def _SetFileChunks(self, path, contents):
    """Put individual file chunks."""
    chunk_keys = []
    entities = []
    index = 1
    for chunk in _SplitByLength(contents, MAX_BYTES_FOR_ENTITY):

      # The chunk might be OK without having the _AhMimicFile entity
      # as a parent so that we can rename the file without moving the
      # actual chunks. However, doing so forces us to retrieve the
      # chunks property (instead of the keys only query) when
      # deleting.
      chunk_key = ndb.Key(pairs=[(self.root.kind(), self.root.id()),
                                 (_AhMimicFile, path),
                                 (_AhMimicChunk, index)],
                          namespace=self.root.namespace())
      chunk_keys.append(chunk_key)
      entities.append(_AhMimicChunk(key=chunk_key, contents=chunk))
      index += 1
    entities.append(_AhMimicFile(id=path, parent=self.root,
                                 chunk_keys=chunk_keys))
    ndb.put_multi(entities)

  def SetFile(self, path, contents):
    if len(contents) > MAX_BYTES_FOR_ENTITY:
      self._SetFileChunks(path, contents)
    else:
      entity = _AhMimicFile(id=path, parent=self.root, contents=contents)
      entity.put()

  def HasDirectory(self, path):
    path = self._NormalizeDirectoryPath(path)
    # always return True for root, even if tree is empty
    if path == '/':
      return True
    for key in _AhMimicFile.query(ancestor=self.root).iter(keys_only=True):
      if key.id().startswith(path):
        return True
    return False

  def ListDirectory(self, path):
    """Enumerate directory contents with leading path."""
    path = self._NormalizeDirectoryPath(path)
    # TODO: optimize by using a more structured tree representation
    keys = _AhMimicFile.query(ancestor=self.root).iter(keys_only=True)
    paths = set()
    for key in keys:
      entry_path = key.id()
      # 'path is None' means get all files recursively
      if path is None:
        paths.add(entry_path)
        continue
      if not entry_path.startswith(path):
        continue
      tail = entry_path[len(path):]
      # return tail if tail is a file otherwise return dir name (=first segment)
      subpath = tail.split('/', 1)[0]
      paths.add(subpath)
    return sorted(paths)
