import { useEffect, useRef } from 'react'
import { copy } from '../i18n/en'

export type ThemeMode = 'system' | 'light' | 'dark'

const themeModes: { mode: ThemeMode; label: string }[] = [
  { mode: 'system', label: copy.themeAuto },
  { mode: 'light', label: copy.themeLight },
  { mode: 'dark', label: copy.themeDark },
]

type SettingsMenuProps = { themeMode: ThemeMode; onThemeMode: (mode: ThemeMode) => void }

/** Rarely used preferences live behind one disclosure instead of in the top bar. */
export function SettingsMenu({ themeMode, onThemeMode }: SettingsMenuProps) {
  const menuRef = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    const close = (event: Event) => {
      const menu = menuRef.current
      if (!menu?.open) return
      if (event instanceof KeyboardEvent) {
        if (event.key !== 'Escape') return
        menu.open = false
        menu.querySelector('summary')?.focus()
        return
      }
      if (event.target instanceof Node && !menu.contains(event.target)) menu.open = false
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
    }
  }, [])

  return (
    <details ref={menuRef} className="settings-menu">
      <summary aria-label={copy.settings} title={copy.settings}>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
      </summary>
      <div className="settings-panel">
        <span className="eyebrow" id="settings-theme">{copy.theme}</span>
        <div className="segmented" role="group" aria-labelledby="settings-theme">
          {themeModes.map(({ mode, label }) => (
            <button key={mode} type="button" aria-pressed={themeMode === mode} onClick={() => onThemeMode(mode)}>{label}</button>
          ))}
        </div>
      </div>
    </details>
  )
}
