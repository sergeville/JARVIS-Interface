// mock/instruments.js -- SIMULATED INSTRUMENTS, marked DEMO, easily removed.
//
// The goals document's four demonstration instruments: an agent, a project,
// a database, a service. Every one is invented, says so in its name, and
// carries demo: true so the node chrome brands it. Removing them is a
// registry call, never a shell edit -- a test proves the orbit empties.
// Nothing outside app.js may import this module.

/** @type {Object[]} */
export const MOCK_INSTRUMENTS = [
  {
    id: 'demo-agent',
    name: 'Sample Agent (mock)',
    type: 'agent',
    icon: 'AG',
    demo: true,
    description: 'A demonstration agent. It does nothing real (mock).',
    capabilities: [{ id: 'demo-cap', name: 'Answer questions (mock)' }],
    actions: [{ id: 'demo-act', name: 'Run a task (mock)' }],
    panels: [],
    dataSources: [],
    permissions: [{ id: 'demo-perm', description: 'pretend-only (mock)' }],
    events: [],
  },
  {
    id: 'demo-project',
    name: 'Sample Project (mock)',
    type: 'project',
    icon: 'PJ',
    demo: true,
    description: 'A demonstration project shell (mock).',
    capabilities: [],
    actions: [],
    panels: [{ id: 'demo-panel', name: 'Task list (mock)' }],
    dataSources: [],
    permissions: [],
    events: [],
  },
  {
    id: 'demo-database',
    name: 'Sample Database (mock)',
    type: 'database',
    icon: 'DB',
    demo: true,
    capabilities: [],
    actions: [],
    panels: [],
    dataSources: [{ id: 'demo-source', name: 'Mock rows (mock)' }],
    permissions: [],
    events: [],
  },
  {
    id: 'demo-service',
    name: 'Sample Service (mock)',
    type: 'service',
    icon: 'SV',
    demo: true,
    capabilities: [],
    actions: [],
    panels: [],
    dataSources: [],
    permissions: [],
    events: [{ id: 'demo-event', description: 'a pretend heartbeat (mock)' }],
  },
];

/**
 * The states the demo instruments wear at boot -- one of each flavour so
 * the twelve-state chrome has something to show. Applied through the bus
 * like any real status change.
 * @type {Record<string, string>}
 */
export const MOCK_STATUSES = {
  'demo-agent': 'active',
  'demo-project': 'idle',
  'demo-database': 'ready',
  'demo-service': 'offline',
};
