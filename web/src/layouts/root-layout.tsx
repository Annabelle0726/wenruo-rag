import { Outlet } from 'react-router';
import { BreadcrumbBar } from './components/breadcrumb-bar';
import { BreadcrumbTrailProvider } from './components/breadcrumb-context';
import { Header } from './components/header';

export function RootLayoutContainer({ children }: React.PropsWithChildren) {
  return (
    // The trail provider wraps the bar and the page together, so a page below can
    // publish the entity levels the bar renders above it.
    <BreadcrumbTrailProvider>
  {/* 登录后各页面共享这张画布；底纹在内容下方，主题颜色和透明度由主题变量控制。 */}
  <div className="shell-canvas size-full min-w-0 grid grid-flow-col grid-cols-1 grid-rows-[auto_auto_1fr]">
    <div className="glass-header">
      <Header />
    </div>

    <BreadcrumbBar />

    <main className="size-full min-w-0 overflow-hidden">{children}</main>
  </div>
</BreadcrumbTrailProvider>
  );
}

export default function RootLayout() {
  return (
    <RootLayoutContainer>
      <Outlet />
    </RootLayoutContainer>
  );
}
