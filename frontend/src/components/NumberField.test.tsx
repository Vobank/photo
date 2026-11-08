import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup } from '@testing-library/react'

import { NumberField } from './NumberField'

afterEach(cleanup)

function Harness({ initial = null as number | null, step = 1 }) {
  const [v, setV] = useState<number | null>(initial)
  return (
    <>
      <NumberField label="Steps" value={v} onChange={setV} min={1} max={50} step={step} placeholder={8} />
      <output data-testid="out">{v === null ? 'null' : v}</output>
    </>
  )
}

const input = () => screen.getByRole('spinbutton')
const out = () => screen.getByTestId('out').textContent

describe('NumberField', () => {
  it('steps from the placeholder with arrow keys and clamps', () => {
    render(<Harness />)
    fireEvent.keyDown(input(), { key: 'ArrowUp' })
    expect(out()).toBe('9')
    fireEvent.keyDown(input(), { key: 'ArrowUp', shiftKey: true })
    expect(out()).toBe('19')
    for (let i = 0; i < 10; i++) fireEvent.keyDown(input(), { key: 'ArrowUp', shiftKey: true })
    expect(out()).toBe('50')
  })

  it('commits typed values on Enter, accepting a decimal comma', () => {
    render(<Harness step={0.1} />)
    fireEvent.change(input(), { target: { value: '3,5' } })
    fireEvent.keyDown(input(), { key: 'Enter' })
    expect(out()).toBe('3.5')
  })

  it('clearing the field returns to the model default', () => {
    render(<Harness initial={12} />)
    fireEvent.change(input(), { target: { value: '' } })
    fireEvent.blur(input())
    expect(out()).toBe('null')
  })

  it('ignores garbage input', () => {
    render(<Harness initial={12} />)
    fireEvent.change(input(), { target: { value: 'abc' } })
    fireEvent.keyDown(input(), { key: 'Enter' })
    expect(out()).toBe('12')
  })
})
