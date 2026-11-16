import { useMemo, useState } from 'react'
import { classifyRealtimeSendFailure } from '@pocketrealms/host'
import './stat_assignment.css'

const BASE_STATS = [
  'strength',
  'dexterity',
  'constitution',
  'intelligence',
  'wisdom',
  'charisma',
]

const STAT_LABELS = {
  strength: 'Strength',
  dexterity: 'Dexterity',
  constitution: 'Constitution',
  intelligence: 'Intelligence',
  wisdom: 'Wisdom',
  charisma: 'Charisma',
}

function rollStat() {
  const rolls = Array.from(
    { length: 4 },
    () => Math.floor(Math.random() * 6) + 1,
  ).sort((left, right) => left - right)

  return rolls.slice(1).reduce((total, value) => total + value, 0)
}

function createRolledValues() {
  return BASE_STATS.map((_, index) => ({
    id: `roll-${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,
    value: rollStat(),
  }))
}

function normalizeStatAssignmentProps(payload) {
  const props = payload?.props && typeof payload.props === 'object'
    ? payload.props
    : {}
  const submittedPayload = payload?.submitted_payload
    && typeof payload.submitted_payload === 'object'
    ? payload.submitted_payload
    : null
  const stats = Array.isArray(props.stats) && props.stats.length === 6
    ? props.stats
    : BASE_STATS
  const rawValues = Array.isArray(submittedPayload?.values)
    ? submittedPayload.values
    : props.values
  const values = Array.isArray(rawValues) && rawValues.length === 6
    ? rawValues.map((value, index) =>
      typeof value === 'object' && value !== null
        ? {
            id: String(value.id ?? `roll-${index}`),
            value: Number(value.value),
          }
        : {
            id: `roll-${index}`,
            value: Number(value),
          },
    )
    : createRolledValues()

  return {
    method: props.method ?? '4d6_drop_lowest',
    stats,
    values,
    assignments: submittedPayload?.assignments
      && typeof submittedPayload.assignments === 'object'
      ? submittedPayload.assignments
      : props.assignments && typeof props.assignments === 'object'
        ? props.assignments
        : {},
    submitted: Boolean(payload?.submitted),
  }
}

export function StatAssignmentMessage({
  message,
  isRealtimeConnected,
  onMessageUpdated,
  onSendRealtimeCommand,
}) {
  const initialProps = useMemo(
    () => normalizeStatAssignmentProps(message.payload),
    [message.payload],
  )
  const [values, setValues] = useState(initialProps.values)
  const [assignments, setAssignments] = useState(initialProps.assignments)
  const [selectedRollId, setSelectedRollId] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const isSubmitted = initialProps.submitted
  const assignedRollIds = new Set(Object.values(assignments))
  const isComplete = initialProps.stats.every((stat) => assignments[stat])

  function assignedStatForRoll(rollId) {
    return Object.entries(assignments).find(([, value]) => value === rollId)?.[0]
  }

  function assignRollToStat(rollId, stat) {
    if (isSubmitted) {
      return
    }

    setAssignments((currentAssignments) => {
      const nextAssignments = Object.fromEntries(
        Object.entries(currentAssignments).filter(
          ([currentStat, currentRollId]) =>
            currentStat !== stat && currentRollId !== rollId,
        ),
      )
      nextAssignments[stat] = rollId
      return nextAssignments
    })
    setSelectedRollId(null)
  }

  function handleRollClick(rollId) {
    if (isSubmitted) {
      return
    }

    const assignedStat = assignedStatForRoll(rollId)
    if (assignedStat) {
      setAssignments((currentAssignments) => {
        const nextAssignments = { ...currentAssignments }
        delete nextAssignments[assignedStat]
        return nextAssignments
      })
    }

    setSelectedRollId((currentRollId) =>
      currentRollId === rollId ? null : rollId,
    )
  }

  function reroll() {
    setValues(createRolledValues())
    setAssignments({})
    setSelectedRollId(null)
    setErrorMessage('')
  }

  async function submitAssignments() {
    if (!isComplete || isSubmitting || isSubmitted || !isRealtimeConnected) {
      return
    }

    setIsSubmitting(true)
    setErrorMessage('')

    try {
      const actionPayload = {
        method: initialProps.method,
        stats: initialProps.stats,
        values,
        assignments,
      }

      if (!onSendRealtimeCommand) {
        throw new Error('Realtime connection is unavailable.')
      }

      await onSendRealtimeCommand('component.action', {
        message_id: message.archiveId,
        action: 'submit_stat_assignment',
        payload: actionPayload,
      })

      onMessageUpdated(message.id, {
        payload: {
          ...(message.payload ?? {}),
          submitted: true,
          submitted_payload: actionPayload,
        },
      })
    } catch (error) {
      const failure = classifyRealtimeSendFailure(error)
      if (failure === 'unsent') {
        setErrorMessage('Stat assignment was not sent because realtime is unavailable.')
      } else if (failure === 'unknown') {
        setErrorMessage(
          'Stat assignment was interrupted. Completion is unknown; it was not retried.',
        )
      } else {
        setErrorMessage(
          error instanceof Error ? error.message : 'Stat assignment failed.',
        )
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="component-message stat-assignment">
      <div className="stat-rolls" aria-label="Rolled stat values">
        {values.map((roll) => {
          const isAssigned = assignedRollIds.has(roll.id)

          return (
            <button
              className={`stat-roll${
                selectedRollId === roll.id ? ' stat-roll-selected' : ''
              }${isAssigned ? ' stat-roll-assigned' : ''}`}
              draggable={!isSubmitted}
              key={roll.id}
              type="button"
              onClick={() => handleRollClick(roll.id)}
              onDragStart={(event) => {
                event.dataTransfer.setData('text/plain', roll.id)
              }}
              disabled={isSubmitted}
            >
              {roll.value}
            </button>
          )
        })}
      </div>

      <div className="stat-slots" aria-label="Base stat slots">
        {initialProps.stats.map((stat) => {
          const assignedRoll = values.find((roll) => roll.id === assignments[stat])

          return (
            <button
              className={`stat-slot${assignedRoll ? ' stat-slot-filled' : ''}`}
              key={stat}
              type="button"
              onClick={() => {
                if (selectedRollId) {
                  assignRollToStat(selectedRollId, stat)
                }
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                const rollId = event.dataTransfer.getData('text/plain')
                if (rollId) {
                  assignRollToStat(rollId, stat)
                }
              }}
              disabled={isSubmitted}
            >
              <span>{STAT_LABELS[stat] ?? stat}</span>
              <strong>{assignedRoll?.value ?? ' '}</strong>
            </button>
          )
        })}
      </div>

      {errorMessage ? (
        <p className="stat-assignment-error" role="alert">
          {errorMessage}
        </p>
      ) : null}

      <button
        className="stat-assignment-action"
        type="button"
        onClick={isComplete ? submitAssignments : reroll}
        disabled={
          isSubmitting
          || isSubmitted
          || (isComplete && !isRealtimeConnected)
        }
      >
        {isSubmitted ? 'Submitted' : isComplete ? 'Submit' : 'Reroll'}
      </button>
    </div>
  )
}
