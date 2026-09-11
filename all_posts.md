---
layout: default
title: 전체 가이드 목록
permalink: /all_posts.html
---
<h1 class="text-2xl font-bold mb-6">전체 비교 가이드 목록</h1>
<div class="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100">
  {% for post in site.posts %}
  <div class="p-4 flex justify-between items-center hover:bg-slate-50">
    <a href="{{ post.url | relative_url }}" class="font-medium text-slate-800 hover:text-blue-600">{{ post.title }}</a>
    <span class="text-xs text-slate-400 shrink-0 ml-4">{{ post.date | date: "%Y-%m-%d" }}</span>
  </div>
  {% endfor %}
</div>
