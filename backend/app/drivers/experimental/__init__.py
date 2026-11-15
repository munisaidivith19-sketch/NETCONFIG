"""Experimental drivers (CLAUDE.md 7): MikroTik RouterOS, Huawei VRP, D-Link DGS and TP-Link JetStream.

They are loaded only when ENABLE_EXPERIMENTAL_DRIVERS=true (drivers/registry.py), are labelled "experimental" in
the UI, and cover VLANs, access and trunk ports, the host name and SSH. None of these OSes has a rollback timer
that NetConfig Studio drives, so a failed push needs a manual restore from the backup taken before it.
Commands and sources: docs/drivers/experimental.md.
"""
