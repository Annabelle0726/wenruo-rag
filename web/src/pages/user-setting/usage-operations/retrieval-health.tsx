/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import { useTranslation } from 'react-i18next';
import { ComingDataPanel } from './components/coming-data-panel';

/**
 * Retrieval Health - an HONEST EMPTY STATE, and nothing else.
 *
 * The retrieval-health facts already exist in the product, but they live in the
 * chat/search answer path's own contract, and this console has no read model for
 * them. This view therefore shows no leg status, no degradation verdict and no
 * route list. In particular it never states that a fallback happened: "Lexical
 * retrieval continued" may only be shown when Retrieval Health actually recorded
 * lexical success, and nothing here records anything.
 */
function RetrievalHealth() {
  const { t } = useTranslation();

  return (
    <div className="settings-body">
      <h3 className="settings-section-title">
        {t('usage.retrievalHealth')}
      </h3>

      <ComingDataPanel
        testId="retrieval-health-coming-data"
        tone="unavailable"
        titleKey="usage.retrievalHealthEmptyTitle"
        descriptionKey="usage.retrievalHealthEmptyDescription"
        pendingKeys={[
          'usage.retrievalHealthPendingLegs',
          'usage.retrievalHealthPendingRoutes',
          'usage.retrievalHealthPendingReadModel',
        ]}
      />

      <div className="settings-tile">
        <span className="settings-tile-label">
          {t('usage.retrievalHealthNotClaimedTitle')}
        </span>
        <p className="settings-tile-hint">
          {t('usage.retrievalHealthNotClaimedDescription')}
        </p>
      </div>
    </div>
  );
}

export default RetrievalHealth;
