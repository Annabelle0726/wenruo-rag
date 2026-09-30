import { render, screen } from '@testing-library/react';
import { ModelTypeBadges } from './model-type-badges';
import { TagFilterButton } from './tag-filter-button';

// The badge component reaches the model hooks, whose module chain builds the app
// router at import time (which needs web globals jsdom lacks).
jest.mock('@/hooks/use-llm-request', () => ({
  useFetchInstanceModels: () => ({ data: [], loading: false }),
  useFetchAllAddedModels: () => ({ data: [], isFetched: true }),
  useFetchAddedProviders: () => ({ data: [] }),
  useFetchAvailableProviders: () => ({ data: [] }),
}));

// Every chip on this surface is the settings module's own tag: one squared shape,
// one hairline, and the brand tint reserved for the SELECTED filter. The previous
// chips were flat grey blocks in one state and the theme's ink in the other, which
// read as a different material from the toolbars around them.
describe('model settings chips', () => {
  it('renders a model type as a settings tag', () => {
    const { container } = render(
      <ModelTypeBadges types={['chat']} showEdit={false} />,
    );

    const badge = container.querySelector('.settings-tag');

    expect(badge).not.toBeNull();
    expect(badge?.className).not.toMatch(
      /bg-bg-card|bg-text-primary|rounded-full/,
    );
  });

  it('marks the active tag filter with the brand tint and idles the rest', () => {
    const { rerender } = render(
      <TagFilterButton label="All" count={3} active onClick={jest.fn()} />,
    );

    const active = screen.getByRole('button');

    expect(active.className).toMatch(/settings-tag/);
    expect(active.className).toMatch(/bg-accent-primary-5/);
    expect(active.className).toMatch(/text-accent-primary/);
    expect(active).toHaveAttribute('aria-pressed', 'true');

    rerender(
      <TagFilterButton
        label="All"
        count={3}
        active={false}
        onClick={jest.fn()}
      />,
    );

    const idle = screen.getByRole('button');

    expect(idle.className).toMatch(/settings-tag/);
    // The idle chip may carry the brand tint on HOVER only: an unprefixed fill
    // would make "not selected" look selected.
    expect(idle.className).not.toMatch(/(^|\s)bg-accent-primary-5/);
    expect(idle.className).not.toMatch(/bg-text-primary/);
    expect(idle).toHaveAttribute('aria-pressed', 'false');
  });
});
