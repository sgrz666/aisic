import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { GatePanel } from './GatePanel'

test('explains and confirms the recommended route B', async () => {
  const onConfirm = vi.fn()
  render(
    <GatePanel
      scores={{ information_sufficiency: 25, researchability: 85 }}
      suggestedRoute="B"
      onConfirm={onConfirm}
    />,
  )

  expect(screen.getByText('路径 B')).toBeInTheDocument()
  expect(screen.getByText(/生成问卷或小实验/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '确认路径 B' }))
  expect(onConfirm).toHaveBeenCalledWith('B')
})

