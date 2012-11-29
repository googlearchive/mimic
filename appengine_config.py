"""App Engine configuration file."""

from __mimic import mimic


# pylint: disable-msg=C6409
def namespace_manager_default_namespace_for_request():
  return mimic.GetNamespace()
