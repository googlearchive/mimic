"""App Engine configuration file."""


from __mimic import datastore_tree
from __mimic import mimic

from google.appengine.api import app_identity


mimic_CREATE_TREE_FUNC = datastore_tree.DatastoreTree

hostname = app_identity.get_default_version_hostname()
mimic_CORS_ALLOWED_ORIGINS = [
    'http://{0}'.format(hostname),
    'https://{0}'.format(hostname),
]

# pylint: disable-msg=C6409
def namespace_manager_default_namespace_for_request():
  return mimic.GetNamespace()
