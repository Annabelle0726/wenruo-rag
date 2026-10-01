import { HomeCard } from '@/components/home-card';
import { TooltipProvider } from '@/components/ui/tooltip';
import '@/locales/config';
import { render, screen } from '@testing-library/react';

// The card has two places to put extra content, and they are not interchangeable:
// a title-row chip shares the name's line, while the trailing rail gets the card's
// right edge to itself. A chat card needs the second, so the placement is worth a
// test rather than a comment.
const renderCard = (props: {
  extra?: React.ReactNode;
  trailing?: React.ReactNode;
  leading?: React.ReactNode;
  layout?: 'standard' | 'chat';
}) =>
  render(
    // The title and the description are truncated texts, which are tooltips, and
    // the app supplies the provider at its root.
    <TooltipProvider>
      <HomeCard
        data={{ name: 'Cable QA', description: 'desc', update_time: '2026-09-18' }}
        moreDropdown={<span>more</span>}
        {...props}
      />
    </TooltipProvider>,
  );

describe('HomeCard slots', () => {
  it('puts the trailing rail after the text column, at the card edge', () => {
    const { container } = renderCard({
      trailing: <span data-testid="rail">rail</span>,
    });

    const card = container.querySelector('article');
    const rail = screen.getByTestId('rail');

    expect(card?.lastElementChild).toBe(rail);
    // Which is a sibling of the text column, not inside it: that column keeps
    // `flex-1`, so the rail is pushed to the far right of the card.
    expect(rail.previousElementSibling?.className).toContain('flex-1');
  });

  it('puts a title-row extra inside the header instead', () => {
    const { container } = renderCard({
      extra: <span data-testid="tag">tag</span>,
    });

    const tag = screen.getByTestId('tag');

    expect(container.querySelector('header')?.contains(tag)).toBe(true);
    expect(container.querySelector('article')?.lastElementChild).not.toBe(tag);
  });

  it('lays out chat identity and title above a divider, then date and count', () => {
    const { container } = renderCard({
      layout: 'chat',
      leading: <span data-testid="identity">chat icon</span>,
      trailing: <span data-testid="message-count">57 messages</span>,
    });

    const card = container.querySelector('article');
    const [titleRow, divider, metadataRow] = Array.from(card?.children ?? []);

    expect(titleRow?.contains(screen.getByTestId('identity'))).toBe(true);
    const title = screen.getByRole('heading', { name: 'Cable QA' });
    expect(titleRow?.querySelector('header')?.contains(title)).toBe(true);
    expect(divider?.className).toContain('h-px');
    expect(divider?.className).toContain('opacity-60');
    expect(metadataRow?.contains(screen.getByTestId('message-count'))).toBe(true);
    const time = metadataRow?.querySelector('p');
    expect(time?.className).toContain('text-xs');
    expect(time?.textContent).not.toMatch(/\d{2}:\d{2}:\d{2}/);
    expect(screen.queryByText('desc')).not.toBeInTheDocument();
  });
});
