"""Packaged knowledge-base YAML profiles.

This file makes ``ekte.knowledge.data`` a real subpackage so that
``importlib.resources.files("ekte.knowledge.data")`` resolves the bundled
``*.yaml`` profiles reliably from an installed wheel (not just from a source
checkout). The loader reads the YAML files beside this module.
"""
