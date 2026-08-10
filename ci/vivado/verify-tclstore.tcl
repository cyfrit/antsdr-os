# SPDX-License-Identifier: MIT

if {![info exists ::env(XILINX_TCLAPP_REPO)] ||
    ![file isdirectory $::env(XILINX_TCLAPP_REPO)]} {
  error "XILINX_TCLAPP_REPO must select a local Tcl Store"
}
if {![info exists ::env(XILINX_LOCAL_USER_DATA)] ||
    ![string equal -nocase $::env(XILINX_LOCAL_USER_DATA) "NO"]} {
  error "XILINX_LOCAL_USER_DATA must be disabled"
}

create_project -in_memory
update_ip_catalog
close_project
