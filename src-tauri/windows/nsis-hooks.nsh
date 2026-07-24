; Dhad Desktop NSIS extension hooks.
; Tauri defines MAINBINARYNAME and INSTDIR before these hooks are expanded.

!macro NSIS_HOOK_POSTINSTALL
  DetailPrint "Creating Dhad desktop shortcut"
  CreateShortCut "$DESKTOP\ضاد.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\${MAINBINARYNAME}.exe" 0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Removing Dhad desktop shortcut"
  Delete "$DESKTOP\ضاد.lnk"
!macroend
