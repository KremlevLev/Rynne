!macro NSIS_HOOK_POSTINSTALL
  CreateShortCut "$SMSTARTUP\Rynne Remote Bridge.lnk" "$INSTDIR\rynne-wake\rynne-wake-bridge.exe" "" "$INSTDIR\rynne-wake\rynne-wake-bridge.exe" 0 SW_HIDE
  Exec '"$INSTDIR\rynne-wake\rynne-wake-bridge.exe"'
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::ExecToLog 'taskkill /F /IM rynne-wake-bridge.exe'
  Delete "$SMSTARTUP\Rynne Remote Bridge.lnk"
!macroend
