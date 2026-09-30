import { render, screen } from '@testing-library/react';
import { AppFooter } from '../app-footer';

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        'header.brandShort': '芯导软件',
        'header.heroTitle': '线缆工业智搜 Agent 平台',
        'footer.copyright': '© XD芯导数字科技 | 工业标准与 QC 合规检验系统',
      })[key] ?? key,
  }),
}));

describe('system bottom bar', () => {
  it('states the brand, the product and the copyright, in that order', () => {
    render(<AppFooter />);

    const footer = screen.getByRole('contentinfo');
    const lines = Array.from(footer.querySelectorAll('p')).map((p) =>
      p.textContent?.trim(),
    );

    expect(lines).toEqual([
      '芯导软件',
      '线缆工业智搜 Agent 平台',
      '© XD芯导数字科技 | 工业标准与 QC 合规检验系统',
    ]);
  });

  it('is a normal flow element that cannot cover the page', () => {
    render(<AppFooter />);

    const footer = screen.getByRole('contentinfo');

    expect(footer.className).toContain('shell-footer');
    // No viewport-relative height and no fixed/sticky positioning: the bar closes
    // the content column instead of floating over it.
    expect(footer.className).not.toMatch(/fixed|sticky|absolute/);
    expect(footer.className).toContain('shrink-0');
    expect(footer.className).toContain('mt-auto');
  });

  it('renders no version, build or status claim of its own', () => {
    render(<AppFooter />);

    const text = screen.getByRole('contentinfo').textContent ?? '';

    expect(text).not.toMatch(/v\d+\.\d+|version|build|已上线|运行正常/i);
  });
});
