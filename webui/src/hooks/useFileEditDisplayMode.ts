import { useEffect, useState } from "react";

import {
  LOCAL_PREFS_CHANGED_EVENT,
  LOCAL_PREFS_STORAGE_KEY,
  normalizeFileEditDisplayMode,
  readLocalPreferences,
  type FileEditDisplayMode,
  type LocalPreferences,
} from "@/lib/local-preferences";

export function useFileEditDisplayMode(): FileEditDisplayMode {
  const [mode, setMode] = useState<FileEditDisplayMode>(() =>
    readLocalPreferences().fileEditDisplayMode,
  );

  useEffect(() => {
    const refresh = () => setMode(readLocalPreferences().fileEditDisplayMode);
    const refreshFromStorage = (event: StorageEvent) => {
      if (
        event.storageArea === window.localStorage
        && event.key === LOCAL_PREFS_STORAGE_KEY
      ) {
        refresh();
      }
    };
    const refreshFromLocalPreferenceEvent = (event: Event) => {
      const detail = (event as CustomEvent<Partial<LocalPreferences> | undefined>).detail;
      setMode(
        detail
          ? normalizeFileEditDisplayMode(detail.fileEditDisplayMode)
          : readLocalPreferences().fileEditDisplayMode,
      );
    };
    window.addEventListener("storage", refreshFromStorage);
    window.addEventListener("focus", refresh);
    window.addEventListener(LOCAL_PREFS_CHANGED_EVENT, refreshFromLocalPreferenceEvent);
    return () => {
      window.removeEventListener("storage", refreshFromStorage);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(LOCAL_PREFS_CHANGED_EVENT, refreshFromLocalPreferenceEvent);
    };
  }, []);

  return mode;
}
