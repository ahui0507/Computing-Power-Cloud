<template>
  <div class="auth-shell">
    <aside class="auth-story">
      <router-link to="/" class="brand"
        ><span class="brand-symbol"
          ><el-icon><Cpu /></el-icon></span
        ><span
          >算力云<span class="brand-caption">COMPUTE CONSOLE</span></span
        ></router-link
      >
      <div class="auth-story-copy">
        <p class="eyebrow">YOUR IDEAS. MORE COMPUTE.</p>
        <h2>让每一个想法<br />都有<span>算力</span>支撑。</h2>
        <p>
          灵活申请 GPU，打开熟悉的开发环境。<br />从第一行代码，到下一次突破。
        </p>
        <div class="auth-features">
          <span
            ><el-icon><Cpu /></el-icon>按需使用</span
          ><span
            ><el-icon><Notebook /></el-icon>JupyterLab 开发</span
          ><span
            ><el-icon><FolderChecked /></el-icon>文件持久保存</span
          >
        </div>
      </div>
      <p class="auth-copyright">COMPUTE · CREATE · EXPLORE</p>
    </aside>
    <main class="auth-main">
      <div class="auth-form"><slot /></div>
    </main>
  </div>
</template>
