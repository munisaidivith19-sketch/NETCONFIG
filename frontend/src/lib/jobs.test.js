import { describe, expect, it } from 'vitest'
import { checkNewSecret, phaseStates, pollDelay, secretsNeeded } from './jobs.js'

const job = (status, states) => ({ status, steps: [{ timeline: states.map((state) => ({ state })) }] })

describe('phaseStates', () => {
  it('marks reached phases done and the current one active', () => {
    const s = phaseStates(job('applying', ['ready', 'queued', 'connecting', 'backing_up', 'checking', 'applying']))
    expect(s.map((p) => p.state)).toEqual(['done', 'done', 'done', 'active', 'pending', 'pending'])
  })

  it('marks the last phase reached as failed when the job rolled back', () => {
    const s = phaseStates(job('rolled_back', ['ready', 'queued', 'connecting', 'backing_up', 'checking', 'applying', 'rolling_back', 'rolled_back']))
    expect(s.find((p) => p.id === 'applying').state).toBe('failed')
    expect(s.find((p) => p.id === 'verifying').state).toBe('pending')
  })

  it('shows every phase done on success', () => {
    const all = ['ready', 'queued', 'connecting', 'backing_up', 'checking', 'applying', 'verifying', 'saving', 'success']
    expect(phaseStates(job('success', all)).every((p) => p.state === 'done')).toBe(true)
  })
})

describe('run-time secrets', () => {
  it('knows which plan secrets are needed', () => {
    expect(secretsNeeded({ vlans: [] })).toEqual({ sshUser: null, enableSecret: false })
    expect(secretsNeeded({ ssh: { username: 'netadmin', set_enable_secret: true } })).toEqual({ sshUser: 'netadmin', enableSecret: true })
  })

  it('applies the backend password rules', () => {
    expect(checkNewSecret('', '')).toBe('Required')
    expect(checkNewSecret('short', 'short')).toMatch(/8 to 64/)
    expect(checkNewSecret('has space here', 'has space here')).toMatch(/No spaces/)
    expect(checkNewSecret('Bad#Hash-123', 'Bad#Hash-123')).toMatch(/No spaces/)
    expect(checkNewSecret('Good-Pass-123', 'Other-Pass-123')).toMatch(/do not match/)
    expect(checkNewSecret('Good-Pass-123', 'Good-Pass-123')).toBeNull()
  })
})

it('polls fast while pushing, slowly while waiting, never when finished', () => {
  expect(pollDelay('applying')).toBe(1000)
  expect(pollDelay('awaiting_approval')).toBe(5000)
  expect(pollDelay('success')).toBeNull()
})
