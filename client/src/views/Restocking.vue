<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="initialLoading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="loadError && !hasLoaded" class="error">{{ loadError }}</div>
    <div v-else>
      <!-- Budget control -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
          <span class="budget-readout">{{ formatMoney(budget) }}</span>
        </div>
        <div class="slider-wrap">
          <input
            type="range"
            class="budget-slider"
            min="0"
            :max="sliderMax"
            :step="step"
            v-model.number="budget"
            :disabled="maxBudget === 0"
            :style="{ '--fill': fillPercent + '%' }"
            :aria-label="t('restocking.budget')"
          />
          <div class="slider-scale">
            <span>{{ formatMoney(0) }}</span>
            <span>{{ formatMoney(maxBudget) }}</span>
          </div>
          <p class="hint">{{ t('restocking.maxHint', { amount: formatMoney(maxBudget) }) }}</p>
        </div>
      </div>

      <div v-if="loadError" class="error">{{ loadError }}</div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatMoney(budget) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.plannedSpend') }}</div>
          <div class="stat-value">{{ formatMoney(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatMoney(remaining) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.itemsToOrder') }}</div>
          <div class="stat-value">{{ items.length }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.estimatedLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: maxLeadTime }) }}</div>
        </div>
      </div>

      <!-- Confirmation / error from placing an order -->
      <div v-if="placedOrder" class="notice success-notice">
        <strong>{{ t('restocking.orderPlaced', { number: placedOrder.order_number }) }}</strong>
        <span>
          {{ t('restocking.leadTimeDelivery', {
            days: placedOrder.lead_time_days,
            date: formatDate(placedOrder.expected_delivery)
          }) }}
        </span>
        <router-link to="/orders" class="notice-link">{{ t('restocking.viewInOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="notice error-notice">{{ submitError }}</div>

      <div class="card" :class="{ refreshing: fetching }">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ items.length }})</h3>
          <button
            type="button"
            class="place-btn"
            :disabled="items.length === 0 || submitting || fetching"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="items.length === 0" class="empty">
          {{ maxBudget === 0 ? t('restocking.nothingNeeded') : t('restocking.noItemsFit') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.name') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.shortfall') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineCost') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.item_sku">
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>{{ item.category }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ trendLabel(item.trend) }}</span>
                </td>
                <td class="num">{{ item.shortfall.toLocaleString() }}</td>
                <td class="num">{{ item.recommended_qty.toLocaleString() }}</td>
                <td class="num">{{ formatMoney(item.unit_cost, true) }}</td>
                <td class="num"><strong>{{ formatMoney(item.line_cost) }}</strong></td>
                <td class="num">{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { convertAmount } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName } = useI18n()

    const initialLoading = ref(true)
    const hasLoaded = ref(false)
    const loadError = ref(null)
    const fetching = ref(false)
    const submitting = ref(false)
    const submitError = ref(null)
    const placedOrder = ref(null)

    const budget = ref(0)
    const maxBudget = ref(0)
    const totalCost = ref(0)
    const remaining = ref(0)
    const items = ref([])

    // Money is held in USD (API currency) and converted only for display
    const currencySymbol = computed(() => (currentCurrency.value === 'JPY' ? '¥' : '$'))
    const formatMoney = (amountUsd, withDecimals = false) => {
      const converted = convertAmount(Number(amountUsd) || 0, currentCurrency.value)
      // Unit costs can have cents in USD; JPY is already rounded by convertAmount
      const digits = withDecimals && currentCurrency.value !== 'JPY' ? 2 : 0
      return currencySymbol.value + converted.toLocaleString(
        currentLocale.value === 'ja' ? 'ja-JP' : 'en-US',
        { minimumFractionDigits: digits, maximumFractionDigits: digits }
      )
    }

    // Smaller step for small catalogs so the slider is still usable
    const step = computed(() => (maxBudget.value < 5000 ? 10 : 100))
    // Round the slider max up to a multiple of step so the thumb can reach
    // max_budget exactly; the backend caps spend at the real maximum anyway.
    const sliderMax = computed(() => Math.ceil(maxBudget.value / step.value) * step.value)
    const fillPercent = computed(() =>
      sliderMax.value > 0 ? Math.min(100, (budget.value / sliderMax.value) * 100) : 0
    )

    // Longest lead time among selected items drives the overall estimate
    const maxLeadTime = computed(() =>
      items.value.reduce((max, i) => Math.max(max, i.lead_time_days || 0), 0)
    )

    const trendLabel = (trend) => {
      const key = `trends.${trend}`
      const label = t(key)
      return label === key ? trend : label
    }

    const formatDate = (dateString) => {
      const d = new Date(dateString)
      if (isNaN(d.getTime())) return '-'
      return d.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
      })
    }

    // Monotonic request counter: only the latest request may write state,
    // so a slow earlier response cannot overwrite a newer one.
    let requestSeq = 0
    const fetchRecommendations = async () => {
      const seq = ++requestSeq
      fetching.value = true
      try {
        const data = await api.getRestockingRecommendations(budget.value)
        if (seq !== requestSeq) return // stale
        maxBudget.value = data.max_budget
        totalCost.value = data.total_cost
        remaining.value = data.remaining
        items.value = data.items
        loadError.value = null
        hasLoaded.value = true
      } catch (err) {
        if (seq !== requestSeq) return
        loadError.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        if (seq === requestSeq) fetching.value = false
      }
    }

    // Debounce slider movement to avoid one request per step
    let debounceTimer = null
    watch(budget, () => {
      if (initialLoading.value) return
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(fetchRecommendations, 200)
    })

    const placeOrder = async () => {
      if (items.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      placedOrder.value = null
      try {
        placedOrder.value = await api.placeRestockingOrder({
          budget: budget.value,
          items: items.value.map(i => ({ item_sku: i.item_sku, quantity: i.recommended_qty }))
        })
        await fetchRecommendations()
      } catch (err) {
        // Backend validation errors (400) carry a human-readable detail
        const detail = err.response?.data?.detail
        submitError.value = typeof detail === 'string'
          ? detail
          : t('restocking.orderFailed')
      } finally {
        submitting.value = false
      }
    }

    onMounted(async () => {
      // budget=0 returns no items but reports max_budget, which sizes the slider
      await fetchRecommendations()
      if (hasLoaded.value && maxBudget.value > 0) {
        // Start at ~50% of max, snapped to the slider step. Set before clearing
        // initialLoading so the watcher does not trigger a duplicate fetch.
        budget.value = Math.round((maxBudget.value * 0.5) / step.value) * step.value
        await fetchRecommendations()
      }
      initialLoading.value = false
    })

    onBeforeUnmount(() => clearTimeout(debounceTimer))

    return {
      t, initialLoading, hasLoaded, loadError, fetching, submitting, submitError, placedOrder,
      budget, maxBudget, totalCost, remaining, items, step, sliderMax, fillPercent,
      maxLeadTime, formatMoney, trendLabel, formatDate, placeOrder, translateProductName
    }
  }
}
</script>

<style scoped>
.budget-readout {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.slider-wrap {
  padding: 0.5rem 0.25rem 0.25rem;
}

/* Custom range slider: slate track, blue filled portion (via --fill) and thumb */
.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 8px;
  border-radius: 4px;
  outline: none;
  cursor: pointer;
  background: linear-gradient(to right, #3b82f6 0%, #3b82f6 var(--fill), #e2e8f0 var(--fill), #e2e8f0 100%);
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.35);
}

.budget-slider::-moz-range-track {
  height: 8px;
  border-radius: 4px;
  background: #e2e8f0;
}

.budget-slider::-moz-range-progress {
  height: 8px;
  border-radius: 4px;
  background: #3b82f6;
}

.budget-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #3b82f6;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.35);
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.4);
}

.budget-slider:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.slider-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

.hint {
  margin: 0.5rem 0 0;
  font-size: 0.813rem;
  color: #64748b;
}

.notice {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.success-notice {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}

.error-notice {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.notice-link {
  color: #2563eb;
  font-weight: 500;
}

.place-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  font-weight: 600;
  cursor: pointer;
}

.place-btn:hover:not(:disabled) {
  background: #2563eb;
}

.place-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.refreshing .table-container {
  opacity: 0.6;
  transition: opacity 0.15s;
}

.empty {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.num {
  text-align: right;
}
</style>
