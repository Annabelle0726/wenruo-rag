import { act, fireEvent, render, screen } from '@testing-library/react';
import { ReferenceImageList } from '../reference-image-list';

/**
 * The fullscreen viewer is driven by the REAL `react-photo-view` here. The defect
 * this file pins down is a registration race between this component and the
 * library, and the sibling suite — which mocks the library out to test the
 * citation mapping — cannot see it: with a mock, five figures that were never
 * registered still look like five figures.
 *
 * `mockPendingSources` hands each pending figure a resolver so a test can settle
 * every URL of one answer inside a single React batch, which is how the running
 * app receives them: the blob requests started from one message come back
 * together.
 */
const mockPendingSources = new Map<string, (url: string) => void>();

jest.mock('@/components/image', () => {
  const ReactModule = jest.requireActual('react');

  return {
    __esModule: true,
    // `forwardRef` because the viewer measures this element to animate the open
    // transition from the thumbnail; a plain function component cannot be given
    // one and would leave that measurement empty.
    default: ReactModule.forwardRef(
      (
        { id, label, ...rest }: { id: string; label?: string },
        ref: React.Ref<HTMLDivElement>,
      ) => (
        <div
          ref={ref}
          data-testid="doc-image"
          data-id={id}
          data-label={label ?? ''}
          {...rest}
        />
      ),
    ),
    useDocumentImageUrl: (id: string) => {
      const [url, setUrl] = ReactModule.useState('');

      ReactModule.useEffect(() => {
        let alive = true;
        mockPendingSources.set(id, (value: string) => {
          if (alive) {
            setUrl(value);
          }
        });
        return () => {
          alive = false;
        };
      }, [id]);

      return url;
    },
  };
});

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) =>
      key === 'common.imageLoadFailed' ? '图片加载失败' : key,
  }),
}));

jest.mock('@/components/ui/carousel', () => ({
  __esModule: true,
  Carousel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CarouselContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CarouselItem: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CarouselPrevious: () => null,
  CarouselNext: () => null,
}));

const referenceChunks = Array.from({ length: 5 }, (_, index) => ({
  id: `chunk-${index + 1}`,
  image_id: `kb-${index + 1}`,
  doc_type: 'image',
})) as never;

// The answer cites the whole pool, so the carousel holds five figures and the
// viewer opens with three slides around the one that was clicked.
const messageContent =
  '老化前抗张强度为 10.0 N/mm² [ID:1]，护套为 PUR 紫色 [ID:2]，' +
  '见表 3 [ID:3]，终端尾管外绝缘 [ID:4]，接地箱防护等级 IP68 [ID:5]。';

const renderCitedFigures = () =>
  render(
    <ReferenceImageList
      referenceChunks={referenceChunks}
      messageContent={messageContent}
    />,
  );

/** Settles every figure's URL in one batch, the way one answer's requests land. */
const settleEveryUrl = async () => {
  const resolvers = [...mockPendingSources.entries()];
  expect(resolvers).toHaveLength(5);

  await act(async () => {
    resolvers.forEach(([id, resolve]) => resolve(`blob:${id}`));
  });
};

const clickFigure = (label: string) => {
  const thumbnail = screen
    .getAllByTestId('doc-image')
    .find((element) => element.dataset.label === label);
  expect(thumbnail).toBeDefined();

  fireEvent.click(thumbnail as HTMLElement);
};

const viewerCounter = () =>
  document.querySelector('.PhotoView-Slider__Counter')?.textContent ?? null;

/** The src of every slide the viewer renders, in slide order. */
const renderedSlides = () =>
  [...document.querySelectorAll('.PhotoView__PhotoWrap')].map(
    (slide) =>
      slide.querySelector('.PhotoView__Photo')?.getAttribute('src') ?? '',
  );

describe('reference figure fullscreen viewer', () => {
  beforeEach(() => {
    mockPendingSources.clear();
  });

  it('registers a figure only once its URL exists, so the viewer never opens on a slide with no image', async () => {
    renderCitedFigures();

    // Before the blob URLs arrive the thumbnails are still shown, but clicking
    // one must not open a viewer: a view registered with the empty string the
    // resolver starts from renders as a slide with no <img>, and three of those
    // on react-photo-view's black backdrop is a black fullscreen area behind a
    // working toolbar and counter.
    clickFigure('[3]');
    expect(document.querySelector('.PhotoView-Portal')).toBeNull();

    await settleEveryUrl();
    clickFigure('[3]');

    // The third citation of a five-figure pool, exactly as the banner reports it.
    expect(viewerCounter()).toBe('3 / 5');
    expect(renderedSlides()).toEqual(['blob:kb-2', 'blob:kb-3', 'blob:kb-4']);
  });

  it('shows the figure that was clicked as the middle slide, including at the loop seam', async () => {
    renderCitedFigures();
    await settleEveryUrl();

    clickFigure('[5]');

    expect(viewerCounter()).toBe('5 / 5');
    // The window wraps past the end of the pool, so the neighbours come from the
    // other side — the clicked figure stays in the middle slide either way.
    expect(renderedSlides()).toEqual(['blob:kb-4', 'blob:kb-5', 'blob:kb-1']);
  });
});
