import { render, screen } from '@testing-library/react';
import { WikiPreparation } from '../wiki-preparation';

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
jest.mock('react-router', () => ({
  useParams: () => ({ id: 'kb' }),
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => (
    <a href={to}>{children}</a>
  ),
}));
jest.mock('@/utils/request', () => ({ __esModule: true, default: {} }));

const prepared = {
  ready: true,
  can_write: true,
  can_manage_models: true,
  building: false,
  parsed_files: 6,
  total_files: 6,
  pipeline_id: 'existing-pipeline',
  checks: { parsed: true, pipeline: true, template: true, models: true },
  models: ['configured-model'],
  stored_dimensions: [1024],
  compatibility: 'isolated_rebuild',
};

test('reuses an existing pipeline and shows actual parsed count and dimensions', () => {
  render(<WikiPreparation data={prepared} failed={false} />);
  expect(screen.getByText(/\(6\/6\)/)).toBeInTheDocument();
  expect(screen.getByText(/1024D/)).toBeInTheDocument();
  const links = screen.getAllByRole('link').map((a) => a.getAttribute('href'));
  expect(links).toContain('/agent/existing-pipeline');
  expect(links).not.toContain('/agents');
});

test('read-only viewers see guidance but no configuration links', () => {
  render(
    <WikiPreparation
      data={{
        ...prepared,
        ready: false,
        can_write: false,
        can_manage_models: false,
      }}
      failed={false}
    />,
  );
  expect(screen.queryAllByRole('link')).toHaveLength(0);
  expect(
    screen.getByText('knowledgeCompilation.preparationReadOnly'),
  ).toBeInTheDocument();
});

test('a deleted template is shown as missing, not silently accepted', () => {
  render(
    <WikiPreparation
      data={{
        ...prepared,
        ready: false,
        checks: { ...prepared.checks, template: false },
      }}
      failed={false}
    />,
  );
  expect(
    screen.getByText(/knowledgeCompilation.preparationMissing/),
  ).toBeInTheDocument();
});

test('failed preparation check does not claim readiness', () => {
  render(<WikiPreparation failed />);
  expect(screen.getByRole('status')).toHaveTextContent(
    'knowledgeCompilation.preparationUnavailable',
  );
  expect(screen.queryAllByRole('link')).toHaveLength(0);
});
