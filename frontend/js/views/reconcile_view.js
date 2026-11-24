export const reconcileViewTemplate = `
<section class="grid-2">
  <section class="panel">
    <h2>提单对账</h2>
    <p class="hint">汇总过磅毛重与提单申报吨比对；齐套只认与当前闸代同代的快照，放行行不计快照。</p>
    <div class="form-row">
      <div><label>提单号</label><input v-model="reconCode"/></div>
    </div>
    <div class="actions">
      <button @click="loadReconcile">对账</button>
      <button class="secondary" @click="loadAllReconcile">全量</button>
    </div>
    <div v-if="reconOne" class="detail-box">
      <p>申报 {{ reconOne.declared_gross_t }}t · 过磅合计 {{ reconOne.ticket_sum_t }}t</p>
      <p :class="reconOne.balanced ? 'ok' : 'bad'">{{ reconOne.balanced ? '账实平衡' : '偏差待查' }}</p>
      <p>快照数 {{ reconOne.seal_count }} · 可出证明
        <span :class="reconOne.proof_ready ? 'ok' : 'bad'">{{ reconOne.proof_ready ? '是（齐套）' : '否（假绿禁写）' }}</span>
      </p>
      <p :class="reconOne.snapshot_kit_complete ? 'ok' : 'bad'">
        快照齐套 {{ reconOne.snapshot_kit_complete ? '是' : '否' }}
      </p>
      <p v-if="reconOne.proof_blockers && reconOne.proof_blockers.length" class="bad">
        缺最新闸代快照：{{ reconOne.proof_blockers.join('、') }}
      </p>
      <table v-if="reconOne.tickets && reconOne.tickets.length" class="data-table">
        <thead><tr><th>票号</th><th>状态</th><th>当前闸代</th><th>快照闸代</th><th>齐套</th></tr></thead>
        <tbody>
          <tr v-for="t in reconOne.tickets" :key="t.ticket_code">
            <td>{{ t.ticket_code }}</td>
            <td>{{ t.status }}</td>
            <td>{{ t.generation }}</td>
            <td>{{ t.seal_generation ?? '—' }}</td>
            <td><span class="badge" :class="t.snapshot_complete ? 'pass' : 'fail'">{{ t.snapshot_complete ? '齐套' : '缺快照' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    <ul v-if="reconAllItems.length">
      <li v-for="r in reconAllItems" :key="r.bl_code">
        {{ r.bl_code }} · {{ r.balanced ? '平' : '偏' }} ·
        <span :class="r.proof_ready ? 'ok' : 'bad'">{{ r.proof_ready ? '齐套可证' : '快照不齐' }}</span>
      </li>
    </ul>
  </section>
  <section class="panel">
    <h2>单票证明</h2>
    <div class="form-row"><div><label>票号</label><input v-model="proofCode"/></div></div>
    <div class="actions"><button @click="loadProof">拉证明</button></div>
    <div v-if="proofOne" class="detail-box">
      <p>提单匹配 {{ proofOne.manifest_matches_bl ? '是' : '否' }}</p>
      <p>超重闭环 {{ proofOne.overload_closed ? '是' : '否' }}</p>
      <p>已放行 {{ proofOne.released ? '是' : '否' }}</p>
      <p>当前闸代 {{ proofOne.ticket_generation }} · 快照闸代 {{ proofOne.seal_generation ?? '—' }}</p>
      <p>持有真实快照 {{ proofOne.has_seal ? '是' : '否（放行不等于快照）' }}</p>
      <p><span :class="proofOne.snapshot_complete ? 'ok' : 'bad'">快照齐套 {{ proofOne.snapshot_complete ? '是' : '否' }}</span></p>
      <p :class="proofOne.coherent ? 'ok' : 'bad'">
        一致 {{ proofOne.coherent ? '是' : '否' }} · 可出证明 {{ proofOne.proof_ready ? '是' : '否' }}
      </p>
    </div>
  </section>
</section>
`;