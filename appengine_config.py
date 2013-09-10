"""App Engine configuration file."""

import json


from __mimic import datastore_tree
from __mimic import mimic


from google.appengine.api import app_identity


# pylint: disable-msg=invalid-name
mimic_CREATE_TREE_FUNC = datastore_tree.DatastoreTree

mimic_JSON_ENCODER = json.JSONEncoder()  # pylint: disable-msg=g-bad-name
mimic_JSON_ENCODER.indent = 4
mimic_JSON_ENCODER.sort_keys = True

hostname = app_identity.get_default_version_hostname()

# pylint: disable-msg=g-bad-name
mimic_CORS_ALLOWED_ORIGINS = [
    'http://{0}'.format(hostname),
    'https://{0}'.format(hostname),
]


# pylint: disable-msg=C6409
def namespace_manager_default_namespace_for_request():
  return mimic.GetNamespace()
