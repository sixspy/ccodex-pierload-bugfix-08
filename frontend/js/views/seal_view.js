export const sealViewTemplate = `
<section class="panel">
  <h2>闸代快照</h2>
  <p class="hint">封闸升代写最新闸代清单，是放行与对账齐套的唯一凭据；须先封闸取快照，再凭快照放行，无快照放行零增拒写。</p>
  <div class="form-row">
    <div><label>过磅票</label>
      <select v-model.number="sealForm.ticket_id">
        <option v-for="t in sealableTickets" :key="t.id" :value="t.id">{{ t.ticket_code }}（闸代{{ t.generation }}）</option>
      </select>
    </div>
    <div><label>清单(可空)</label><input v-model="sealForm.manifest"/></div>
  </div>
  <div class="actions">
    <button @click="createSeal">写入快照</button>
    <button class="secondary" @click="refresh">刷新</button>
  </div>
  <table class="data-table">
    <thead><tr><th>快照号</th><th>票号</th><th>快照闸代</th><th>票当前闸代</th><th>清单摘要</th><th>同代状态</th></tr></thead>
    <tbody>
      <tr v-for="s in seals" :key="s.id">
        <td>{{ s.seal_ref }}</td>
        <td>{{ s.ticket_code }}</td>
        <td>{{ s.ticket_generation }}</td>
        <td>{{ s.ticket_generation_now ?? '—' }}</td>
        <td class="mono">{{ shortText(s.manifest) }}</td>
        <td><span class="badge" :class="s.is_latest ? 'pass' : 'fail'">{{ s.is_latest ? '同代齐套' : '代差滞后' }}</span></td>
      </tr>
    </tbody>
  </table>
</section>
`;