import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { BreadcrumbBar } from '../breadcrumb-bar';
import {
  BreadcrumbTrail,
  BreadcrumbTrailProvider,
} from '../breadcrumb-context';

/**
 * The bar resolves the trail from the URL, so this suite is a route table: every
 * console route has to produce the module → entity → sub-page chain, with every
 * level above the last one a link and the last one the page itself.
 *
 * The route constants are stubbed with their real values (importing `@/routes`
 * builds a browser router that jsdom cannot host).
 */
jest.mock('@/routes', () => ({
  Routes: {
    Root: '/',
    Datasets: '/datasets',
    DatasetBase: '/dataset',
    Files: '/files',
    Skills: '/files/skills',
    Dataset: '/dataset/files',
    Agent: '/agent',
    AgentTemplates: '/agent-templates',
    Agents: '/agents',
    Memories: '/memories',
    Memory: '/memory',
    MemoryMessage: '/memory-message',
    MemorySetting: '/memory-setting',
    Searches: '/searches',
    Search: '/search',
    Chats: '/chats',
    Chat: '/chat',
    UserSetting: '/user-setting',
    DatasetTesting: '/retrieval',
    Chunks: '/chunk',
    Compilation: '/compilation',
    KnowledgeGraph: '/knowledge-graph',
    DataSetOverview: '/logs',
    DataSetSetting: '/configuration',
  },
}));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <BreadcrumbTrailProvider>
        <BreadcrumbBar />
      </BreadcrumbTrailProvider>
    </MemoryRouter>,
  );

/** The levels as text, in order, skipping the separators. */
const readLevels = () => {
  const bar = screen.getByLabelText('breadcrumb');
  return within(bar)
    // `hidden` because the separators are `aria-hidden` on purpose and a role
    // query skips those by default.
    .getAllByRole('listitem', { hidden: true })
    .filter((li) => !li.hasAttribute('aria-hidden'))
    .map((li) => ({
      text: li.textContent,
      link: Boolean(li.querySelector('a')),
      current: Boolean(li.querySelector('[aria-current="page"]')),
      chip: Boolean(li.querySelector('.shell-context-current')),
      href: li.querySelector('a')?.getAttribute('href') ?? null,
    }));
};

describe('page context bar', () => {
  const routes: Array<[string, string[], (string | null)[]]> = [
    ['/', ['header.home'], [null]],
    ['/datasets', ['breadcrumb.datasetModule'], [null]],
    [
      '/dataset/files/kb-1',
      ['breadcrumb.datasetModule', 'knowledgeDetails.subbarFiles'],
      ['/datasets', null],
    ],
    [
      '/dataset/retrieval/kb-1',
      ['breadcrumb.datasetModule', 'knowledgeDetails.testing'],
      ['/datasets', null],
    ],
    [
      '/dataset/logs/kb-1',
      ['breadcrumb.datasetModule', 'knowledgeDetails.overview'],
      ['/datasets', null],
    ],
    [
      '/dataset/configuration/kb-1',
      ['breadcrumb.datasetModule', 'knowledgeDetails.configuration'],
      ['/datasets', null],
    ],
    [
      '/dataset/compilation/kb-1',
      ['breadcrumb.datasetModule', 'breadcrumb.artifact'],
      ['/datasets', null],
    ],
    [
      '/dataset/knowledge-graph/kb-1',
      ['breadcrumb.datasetModule', 'knowledgeDetails.knowledgeGraph'],
      ['/datasets', null],
    ],
    [
      '/dataset/kb-1',
      ['breadcrumb.datasetModule', 'knowledgeDetails.subbarFiles'],
      ['/datasets', null],
    ],
    ['/chats', ['header.chat'], [null]],
    // The module alone is the current page until the page publishes its entity, so
    // the single level is never a link.
    ['/chat/chat-1', ['header.chat'], [null]],
    ['/agents', ['header.flow'], [null]],
    ['/agent/agent-1', ['header.flow'], [null]],
    // The template gallery is a page of the agent module with a path of its own,
    // and it must not read as the home route.
    [
      '/agent-templates',
      ['header.flow', 'breadcrumb.agentTemplates'],
      ['/agents', null],
    ],
    ['/searches', ['header.search'], [null]],
    ['/search/search-1', ['header.search'], [null]],
    ['/memories', ['header.memories'], [null]],
    [
      '/memory/memory-message/mem-1',
      ['header.memories', 'breadcrumb.messages'],
      ['/memories', null],
    ],
    [
      '/memory/memory-setting/mem-1',
      ['header.memories', 'breadcrumb.setting'],
      ['/memories', null],
    ],
    ['/files', ['header.fileManager'], [null]],
    [
      '/files/skills',
      ['header.fileManager', 'header.skills'],
      ['/files', null],
    ],
    ['/user-setting/profile', ['header.setting'], [null]],
    // A route the URL alone cannot place still gets a rail rather than an empty strip.
    ['/chunk', ['header.home'], [null]],
  ];

  it.each(routes)('%s renders its module chain', (path, labels, hrefs) => {
    renderAt(path);

    const levels = readLevels();

    expect(levels.map((level) => level.text)).toEqual(labels);
    expect(levels.map((level) => level.href)).toEqual(hrefs);

    // Exactly the last level is the page itself, and it is never a link.
    const current = levels.filter((level) => level.current);
    expect(current).toHaveLength(1);
    expect(levels[levels.length - 1].current).toBe(true);
    expect(levels[levels.length - 1].link).toBe(false);
    expect(levels[levels.length - 1].chip).toBe(true);

    // Every ancestor is a real link, and it carries no fill.
    levels.slice(0, -1).forEach((level) => {
      expect(level.link).toBe(true);
      expect(level.chip).toBe(false);
    });
  });

  it('separates the levels with a chevron each, hidden from the reading order', () => {
    renderAt('/dataset/files/kb-1');

    const bar = screen.getByLabelText('breadcrumb');
    expect(within(bar).getAllByRole('listitem', { hidden: true })).toHaveLength(
      3,
    );
    const separators = Array.from(
      bar.querySelectorAll(':scope > ol > li[aria-hidden="true"]'),
    );
    expect(separators).toHaveLength(1);
    expect(separators[0].querySelector('svg')).toBeTruthy();
    expect(separators[0].textContent).toBe('');
  });

  it('anchors the trail with the brand marker, and carries no rule across the page', () => {
    renderAt('/chats');

    const bar = screen.getByLabelText('breadcrumb');
    expect(bar.querySelector('.shell-context-marker')).toBeTruthy();
    expect(bar.className).toContain('shell-context-bar');
    // The band's structure is the marker, the chevrons and the chip: a hairline
    // running to the right edge read as a hard rule across the page, so the marker
    // is the only direct child span the bar is allowed.
    expect(bar.querySelectorAll(':scope > span')).toHaveLength(1);
    // …and the row stays the short one it always occupied.
    expect(bar.className).toContain('h-8');
  });

  it('folds a published entity level between the module and the sub-page', () => {
    render(
      <MemoryRouter initialEntries={['/dataset/files/kb-1']}>
        <BreadcrumbTrailProvider>
          <BreadcrumbBar />
          <BreadcrumbTrail
            crumbs={[{ label: '国家及行业规范', to: '/datasets' }]}
          />
        </BreadcrumbTrailProvider>
      </MemoryRouter>,
    );

    expect(readLevels().map((level) => level.text)).toEqual([
      'breadcrumb.datasetModule',
      '国家及行业规范',
      'knowledgeDetails.subbarFiles',
    ]);
  });
});
