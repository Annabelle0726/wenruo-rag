import { PageContainer, PageContent } from '@/layouts/components/page-container';
import { AppFooter } from '@/layouts/components/app-footer';
import { Applications } from './applications';
import { Datasets } from './datasets';

const Home = () => {
  return (
    // A flex column so the footer's `mt-auto` closes the page at the bottom of the
    // scroll region: with content shorter than the viewport the bottom bar sits on
    // the page's own last edge instead of floating in the middle of it, and with
    // longer content it simply follows the content.
    <PageContainer className="flex min-h-0 flex-col pt-4 pb-0">
      <PageContent>
        {/* The 查询条件 panel at the head of the knowledge-base section is the
            page's first element, so the operator lands on the search form and the
            data table it drives instead of a marketing banner. */}
        <article className="pb-6">
          <Datasets />
          <Applications />
        </article>
      </PageContent>

      <AppFooter />
    </PageContainer>
  );
};

export default Home;
