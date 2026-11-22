// Einstieg des Plugins (ein Hook-Modul pro Plugin): Menü /walkie + Brücke zur Walkie-App.
import type { Register } from 'claude-code'

import { menuStart, register as menu } from './menu'
import { sessionStart, register as session } from './session'

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    const res = await next(e)
    await menuStart($)
    await sessionStart($, e.isInteractive !== false)
    return res
  })
  menu(on, options)
  session(on, options)
}
