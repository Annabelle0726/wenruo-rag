const { fontFamily } = require('tailwindcss/defaultTheme');

/** @type {import('tailwindcss').Config} */

module.exports = {
  darkMode: ['selector'],
  content: [
    // Every source file, not just the three folders that hold components: a
    // class name can live in a shared constant (the industrial category tones
    // do), and Tailwind tree-shakes @layer components against these globs — so a
    // class referenced only from an unscanned folder is dropped from the bundle
    // without a warning.
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1536px',
      },
    },
    screens: {
      sm: '640px',
      md: '768px',
      lg: '1024px',
      xl: '1280px',
      '2xl': '1536px',
      '3xl': '1780px',
      '4xl': '1980px',
    },
    extend: {
      borderWidth: {
        0.5: '0.5px',
      },
      colors: {
        border: 'var(--border-default)',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'var(--background)',
        foreground: 'var(--colors-text-neutral-strong)',
        buttonBlueText: 'var(--button-blue-text)',

        'colors-outline-sentiment-primary':
          'var(--colors-outline-sentiment-primary)',
        'colors-outline-neutral-strong': 'var(--colors-outline-neutral-strong)',
        'colors-outline-neutral-standard':
          'var(--colors-outline-neutral-standard)',

        'colors-text-neutral-strong': 'var(--colors-text-neutral-strong)',
        'colors-text-neutral-standard': 'var(--colors-text-neutral-standard)',

        'text-badge': 'var(--text-badge)',
        'text-title': 'var(--text-title)',
        'text-sub-title': 'var(--text-sub-title)',
        'text-sub-title-invert': 'var(--text-sub-title-invert)',
        'text-title-invert': 'var(--text-title-invert)',
        'background-header-bar': 'var(--background-header-bar)',
        'background-card': 'var(--background-card)',
        'background-highlight': 'var(--background-highlight)',

        'input-border': 'var(--input-border)',

        /* design colors */
        'bg-title': 'var(--bg-title)',
        'bg-base': 'var(--bg-base)',
        'bg-card': 'var(--bg-card)',
        'bg-component': 'var(--bg-component)',
        'bg-input': 'var(--bg-input)',
        'bg-canvas': {
          DEFAULT: 'rgb(var(--bg-canvas) / <alpha-value>)',
        },
        'bg-list': {
          DEFAULT: 'rgb(var(--bg-list) / <alpha-value>)',
        },
        'text-primary': {
          DEFAULT: 'rgb(var(--text-primary) / <alpha-value>)',
        },
        'text-primary-inverse': {
          DEFAULT: 'rgb(var(--text-primary-inverse) / <alpha-value>)',
        },
        'text-secondary': {
          DEFAULT: 'rgb(var(--text-secondary) / <alpha-value>)',
        },
        'text-secondary-inverse': {
          DEFAULT: 'rgb(var(--text-secondary-inverse) / <alpha-value>)',
        },
        'text-disabled': 'var(--text-disabled)',
        'border-default': 'var(--border-default)',
        'border-accent': 'var(--border-accent)',
        'border-button': 'var(--border-button)',
        'accent-primary': {
          DEFAULT: 'rgb(var(--accent-primary) / <alpha-value>)',
          5: 'rgba(var(--accent-primary) / 0.05)', // 5%
        },
        'bg-accent': 'var(--bg-accent)',
        'state-success': {
          DEFAULT: 'rgb(var(--state-success) / <alpha-value>)',
          5: 'rgba(var(--state-success) / 0.05)', // 5%
        },
        'state-warning': {
          DEFAULT: 'rgb(var(--state-warning) / <alpha-value>)',
          5: 'rgba(var(--state-warning) / 0.05)', // 5%
        },
        'state-error': {
          DEFAULT: 'rgb(var(--state-error) / <alpha-value>)',
          5: 'rgba(var(--state-error) / 0.05)', // 5%
        },
        'team-group': 'var(--team-group)',
        'team-member': 'var(--team-member)',
        'team-department': 'var(--team-department)',
        'bg-member': 'var(--bg-member)',

        /* cable industry theme (see tailwind.css :root / .dark) */
        'cable-page-from': 'var(--cable-page-from)',
        'cable-page-to': 'var(--cable-page-to)',
        'cable-surface': {
          DEFAULT: 'var(--cable-surface)',
          muted: 'var(--cable-surface-muted)',
        },
        'cable-border': {
          DEFAULT: 'var(--cable-surface-border)',
          hover: 'var(--cable-surface-border-hover)',
        },
        'cable-brand': {
          DEFAULT: 'var(--cable-brand)',
          soft: 'var(--cable-brand-soft)',
        },
        'cable-accent': 'var(--cable-accent)',
        'cable-copper': 'var(--cable-copper)',
        'cable-icon': {
          DEFAULT: 'var(--cable-icon-surface)',
          foreground: 'var(--cable-icon-foreground)',
        },
        'cable-divider': 'var(--cable-divider)',
        'cable-muted': 'var(--cable-muted)',
        /* Data-table surfaces: the sunk header and the row sheen, resolved from
           tokens so light and dark switch in one place. */
        'table-header': 'var(--table-header-bg)',
        'table-row-hover': 'var(--table-row-hover)',
        'table-row-base': 'var(--table-row-base)',
        'table-row-alternate': 'var(--table-row-alternate)',
        /* Semantic content scale: text is coloured by role, and both themes
           resolve it from the tokens declared in tailwind.css. */
        content: {
          primary: 'var(--content-primary)',
          secondary: 'var(--content-secondary)',
          tertiary: 'var(--content-tertiary)',
        },
        'cable-hairline': 'var(--cable-hairline)',
        'cable-backdrop': 'var(--cable-backdrop)',
        'cable-avatar': {
          DEFAULT: 'var(--cable-avatar-surface)',
          foreground: 'var(--cable-avatar-foreground)',
        },
        /* Tech accent and glass surfaces. Every value resolves from a CSS
           variable, so no component hard-codes a colour and the dark switch is a
           token swap. */
        'accent-color': {
          DEFAULT: 'var(--accent-color)',
          strong: 'var(--accent-color-strong)',
          soft: 'var(--accent-color-soft)',
        },
        /* Ink that sits on the accent itself. The class `text-accent-contrast` is
           already used by the theme switch and the sign-in language switch, but
           the colour key was never declared, so the utility was missing from the
           generated CSS and those controls silently inherited their text colour. */
        'accent-contrast': 'var(--accent-contrast)',
        glass: {
          DEFAULT: 'var(--glass-bg)',
          border: 'var(--glass-border)',
        },
        'surface-hover': {
          DEFAULT: 'var(--surface-hover-bg)',
          border: 'var(--surface-hover-border)',
        },
        /* Sign-in hero column: the title ramp, the feature cards and the badges.
           Light and dark carry different primitives (see tailwind.css), so the
           component names them by role instead of by colour. */
        'hero-title-from': 'var(--hero-title-from)',
        'hero-title-via': 'var(--hero-title-via)',
        'hero-title-to': 'var(--hero-title-to)',
        'hero-card': {
          DEFAULT: 'var(--hero-card-bg)',
          hover: 'var(--hero-card-bg-hover)',
          border: 'var(--hero-card-border)',
        },
        'hero-icon': 'var(--hero-icon)',
        'hero-badge': {
          DEFAULT: 'var(--hero-badge-bg)',
          border: 'var(--hero-badge-border)',
          text: 'var(--hero-badge-text)',
        },
        'hero-glow': 'var(--hero-glow)',
        'login-card-edge': 'var(--login-card-edge)',
        /* Ceramic shell edge: the hairline that wraps the pill and the cards,
           with a brighter variant for hover. */
        'ceramic-border': {
          DEFAULT: 'var(--ceramic-border)',
          hover: 'var(--ceramic-border-hover)',
        },
        'cable-nav': {
          DEFAULT: 'var(--cable-nav-text)',
          'text-hover': 'var(--cable-nav-text-hover)',
          'active-text': 'var(--cable-nav-active-text)',
          'active-bg': 'var(--cable-nav-active-bg)',
          indicator: 'var(--cable-nav-indicator)',
        },

        /* 深绿顶栏：全宽实心国网绿；`hover` 是加深色，Hover 与选中态共用它，
           选中态另加 2px 白线与加粗（见 tailwind.css 的 .gov-nav-link-active）。 */
        'gov-header': {
          DEFAULT: 'var(--gov-header-bg)',
          hover: 'var(--gov-header-hover)',
          fg: 'var(--gov-header-fg)',
          border: 'var(--gov-header-border)',
        },
        /* 工业级面板与数据表格的 1px 实线边框。 */
        'panel-border': 'var(--panel-border)',
        'table-border': 'var(--table-border)',
        'table-head-ink': 'var(--table-head-ink)',
        /* 状态徽标：可用（绿）/ 已归档（灰）。 */
        'status-available': {
          DEFAULT: 'var(--status-available-surface)',
          ink: 'var(--status-available-ink)',
          border: 'var(--status-available-border)',
        },
        'status-archived': {
          DEFAULT: 'var(--status-archived-surface)',
          ink: 'var(--status-archived-ink)',
          border: 'var(--status-archived-border)',
        },

        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'var(--background-inverse-strong)',
          foreground: 'var(--background-inverse-strong-foreground)',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'var(--background-inverse-standard)',
          foreground: 'var(--background-inverse-standard-foreground)',
        },
        backgroundCoreWeak: 'var(--background-core-weak)',
        'colors-background-neutral-standard': {
          DEFAULT: 'var(--colors-background-neutral-standard)',
          foreground: 'var(--background-inverse-standard-foreground)',
        },
        sidebar: {
          DEFAULT: 'hsl(var(--sidebar-background))',
          foreground: 'hsl(var(--sidebar-foreground))',
          primary: 'hsl(var(--sidebar-primary))',
          'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
          accent: 'hsl(var(--sidebar-accent))',
          'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
          border: 'hsl(var(--sidebar-border))',
          ring: 'hsl(var(--sidebar-ring))',
        },
      },
      /* 无渐变设计：不再声明任何 backgroundImage 工具类。 */
      /* 政企后台用 1px 实线边框划定区域，不用悬浮阴影：默认阴影标尺整体归零，
         历史 class 名（shadow-sm / shadow-lg / shadow-2xl…）仍然可写但不再投影。 */
      boxShadow: {
        none: 'none',
        xs: 'none',
        sm: 'none',
        DEFAULT: 'none',
        md: 'none',
        lg: 'none',
        xl: 'none',
        '2xl': 'none',
        inner: 'none',
        /* Cable surfaces: flat in both themes. */
        'cable-surface': 'var(--cable-shadow)',
        'cable-surface-hover': 'var(--cable-shadow-hover)',
        'cable-drawer': 'var(--cable-drawer-shadow)',
        /* 主操作强调色不再发光。 */
        'accent-glow': 'none',
        ceramic: 'var(--ceramic-elevation)',
        'ceramic-hover': 'var(--ceramic-elevation-hover)',
        'login-card': 'var(--login-card-glow)',
      },
      /* 工业级直角：整条圆角标尺压到 2px，任何历史 class（含 rounded-full、
         rounded-xl…）都保留名字但只渲染 2px 直角，胶囊与圆角胶囊从此不可能出现。 */
      borderRadius: {
        none: '0px',
        px: '1px',
        '3xs': '2px',
        '2xs': '2px',
        xs: '2px',
        sm: '2px',
        DEFAULT: '2px',
        md: '2px',
        lg: '2px',
        xl: '2px',
        '2xl': '2px',
        '3xl': '2px',
        '4xl': '2px',
        full: '2px',
      },
      fontFamily: {
        /* 国网/政企系统标准中文无衬线字体栈 */
        sans: [
          '"Microsoft YaHei"',
          '"微软雅黑"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          'Arial',
          'sans-serif',
        ],
        mono: ['Consolas', '"Courier New"', 'SimSun', '"宋体"', 'monospace'],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
        'caret-blink': {
          '0%,70%,100%': { opacity: '1' },
          '20%,50%': { opacity: '0' },
        },
        'spin-reverse': {
          from: { transform: 'rotate(0deg)' },
          to: { transform: 'rotate(-360deg)' },
        },
        'bell-shake': {
          '0%,25%': { transform: 'rotate(0)', transformOrigin: 'center 25% ' },
          '3.125%': { transform: 'rotate(-12.5deg)' },
          '9.375%': { transform: 'rotate(11deg)' },
          '15.625%': { transform: 'rotate(-9.5deg)' },
          '21.875%': { transform: 'rotate(7.5deg)' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'caret-blink': 'caret-blink 1.25s ease-out infinite',
        'spin-reverse': 'spin-reverse 1s linear infinite',
        'bell-shake':
          'bell-shake 2s 1s cubic-bezier(0.33, 1, 0.68, 1) infinite',
      },
    },
  },
  plugins: [
    require('tailwindcss-animate'),
    require('tailwind-scrollbar'),
    require('@tailwindcss/container-queries'),
    require('@tailwindcss/typography'),
  ],
};
