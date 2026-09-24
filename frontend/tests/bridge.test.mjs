import test from 'node:test'
import assert from 'node:assert/strict'
import { call, waitForDesktop } from '../src/lib/bridge.ts'
import { price, percent, safeUrl } from '../src/lib/format.ts'

test('bridge waits for injection and sends zero arguments to local bootstrap', async () => {
  global.window = Object.assign(new EventTarget(), {setTimeout})
  const pending = waitForDesktop()
  let argsSeen
  window.pywebview = { api: { workspace_bootstrap: async (...args) => { argsSeen = args; return {ok: true, data: {strategies: []}} } } }
  window.dispatchEvent(new Event('pywebviewready'))
  await pending
  assert.deepEqual(await call('workspace_bootstrap'), {strategies: []})
  assert.deepEqual(argsSeen, [])
  window.pywebview.api.rename = async () => ({ok: false, error: '名称不能为空'})
  await assert.rejects(call('rename', {name: ''}), /名称不能为空/)
})
test('missing prices and zero values remain distinct; unsafe source links are omitted', () => {
  assert.equal(price(null), '—')
  assert.equal(price(0), '0.00')
  assert.equal(percent(-1.23), '-1.23%')
  assert.equal(safeUrl('javascript:alert(1)'), undefined)
  assert.equal(safeUrl('https://example.com/'), 'https://example.com/')
})
