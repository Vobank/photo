import { type KeyboardEvent, type PointerEvent, useId, useRef, useState } from 'react'

import styles from './Field.module.css'

interface NumberFieldProps {
  label: string
  value: number | null
  onChange: (value: number | null) => void
  min: number
  max: number
  step?: number
  /** Shown (dimmed) when value is null, e.g. the model's default. */
  placeholder?: number
  /** Pixels of horizontal drag per step when scrubbing the label. */
  dragPixelsPerStep?: number
  disabled?: boolean
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))

/**
 * Numeric input whose label can be dragged horizontally to scrub the value,
 * as in design and 3D tools. Arrow keys step; Shift multiplies by 10.
 */
export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  placeholder,
  dragPixelsPerStep = 6,
  disabled,
}: NumberFieldProps) {
  const id = useId()
  // A draft is only shown while it belongs to the current value; external changes discard it.
  const [draftState, setDraftState] = useState<{ text: string; base: number | null } | null>(null)
  const draft = draftState && draftState.base === value ? draftState.text : null
  const setDraft = (text: string | null) => setDraftState(text === null ? null : { text, base: value })
  const drag = useRef<{ x: number; start: number } | null>(null)
  const decimals = (String(step).split('.')[1] ?? '').length
  const round = (v: number) => Number(clamp(v, min, max).toFixed(decimals))
  const shown = value ?? placeholder ?? min

  const commit = (text: string) => {
    setDraft(null)
    if (text.trim() === '') {
      onChange(null)
      return
    }
    const parsed = Number(text.replace(',', '.'))
    if (Number.isFinite(parsed)) onChange(round(parsed))
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      const delta = (e.key === 'ArrowUp' ? step : -step) * (e.shiftKey ? 10 : 1)
      onChange(round(shown + delta))
    } else if (e.key === 'Enter') {
      commit(e.currentTarget.value)
    } else if (e.key === 'Escape') {
      setDraft(null)
      e.currentTarget.blur()
    }
  }

  const onPointerDown = (e: PointerEvent<HTMLLabelElement>) => {
    if (disabled || e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, start: shown }
  }
  const onPointerMove = (e: PointerEvent<HTMLLabelElement>) => {
    if (!drag.current) return
    const steps = Math.round((e.clientX - drag.current.x) / dragPixelsPerStep)
    const next = round(drag.current.start + steps * step * (e.shiftKey ? 10 : 1))
    if (next !== value) onChange(next)
  }
  const onPointerUp = () => {
    drag.current = null
  }

  return (
    <div className={styles.number}>
      <label
        htmlFor={id}
        className={styles.scrub}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {label}
      </label>
      <input
        id={id}
        className={`${styles.input} num`}
        inputMode="decimal"
        disabled={disabled}
        value={draft ?? (value === null ? '' : String(value))}
        placeholder={placeholder === undefined ? undefined : String(placeholder)}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => draft !== null && commit(e.target.value)}
        onKeyDown={onKeyDown}
        aria-valuemin={min}
        aria-valuemax={max}
        role="spinbutton"
        aria-valuenow={shown}
      />
    </div>
  )
}
