import { test } from 'node:test'
import assert from 'node:assert/strict'
import { hasAutoCourseStartLocationMismatch } from './locationContract.js'

test('nearby automatic-course response is accepted', () => {
  assert.equal(hasAutoCourseStartLocationMismatch(
    { latitude: 37.486890, longitude: 126.929364 },
    { latitude: 37.487001, longitude: 126.929100 },
  ), false)
})

test('wrong-area automatic-course response is rejected', () => {
  assert.equal(hasAutoCourseStartLocationMismatch(
    { latitude: 37.486890, longitude: 126.929364 },
    { latitude: 37.501271, longitude: 126.754157 },
  ), true)
})
