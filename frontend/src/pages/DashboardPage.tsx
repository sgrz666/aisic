import { ArrowRightOutlined, BookOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Card, Form, Input, Modal, Skeleton, Tag, message } from 'antd'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { createProject, listProjects } from '../api'
import { BrandMark } from '../components/BrandMark'
import type { Project } from '../types'

const examples = [
  ['A', '人口变化与基础教育资源配置', '公开数据分析'],
  ['B', '大学生 AI 焦虑与专业关系', '问卷与统计'],
  ['D', '吃饭速度与眨眼频率', '探索性拒答'],
]

export function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((error) => message.error(error.message))
      .finally(() => setLoading(false))
  }, [])

  async function submit(values: { title: string; idea_text: string }) {
    setSubmitting(true)
    try {
      const project = await createProject(values)
      setOpen(false)
      form.resetFields()
      navigate(`/projects/${project.id}`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <BrandMark />
        <div className="dashboard-header__meta">
          <span className="status-dot" /> 本地研究环境
        </div>
      </header>

      <main>
        <section className="hero">
          <div className="hero__gridline" />
          <div className="hero__copy reveal-1">
            <div className="section-kicker">AI SCIENTIST · FOR EDUCATION</div>
            <h1>把模糊的研究灵感，<br />变成可验证的教育研究。</h1>
            <p>证据优先、人在回路、统计可复现。教育智研将 Idea 转化为可追溯的科学假设与研究计划。</p>
            <Button
              type="primary"
              size="large"
              icon={<PlusOutlined />}
              aria-label="创建研究项目"
              onClick={() => setOpen(true)}
            >
              创建研究项目
            </Button>
          </div>
          <div className="hero__artifact reveal-2" aria-hidden="true">
            <div className="artifact-paper artifact-paper--back" />
            <div className="artifact-paper">
              <span>RESEARCH PROTOCOL · 01</span>
              <h3>Evidence → Hypothesis</h3>
              <div className="artifact-line artifact-line--long" />
              <div className="artifact-line" />
              <div className="artifact-route">
                <b>A</b><b className="active">B</b><b>C</b><b>D</b>
              </div>
              <div className="artifact-stamp">可验证</div>
            </div>
          </div>
        </section>

        <section className="content-band">
          <div className="section-heading">
            <div><span className="section-kicker">PROJECT ARCHIVE</span><h2>研究项目</h2></div>
            <span>{projects.length.toString().padStart(2, '0')} 个项目</span>
          </div>
          {loading ? (
            <Skeleton active />
          ) : projects.length ? (
            <div className="project-grid">
              {projects.map((project) => (
                <Link key={project.id} className="project-card-link" to={`/projects/${project.id}`}>
                  <Card className="project-card">
                    <div className="project-card__top"><Tag>{project.stage}</Tag><ArrowRightOutlined /></div>
                    <h3>{project.title}</h3><p>{project.idea_text}</p>
                    <small>{project.evidence_count} 条证据 · 路径 {project.route ?? '待判断'}</small>
                  </Card>
                </Link>
              ))}
            </div>
          ) : (
            <div className="empty-projects"><BookOutlined /><p>还没有研究档案。上面的按钮是第一块拼图。</p></div>
          )}
        </section>

        <section className="example-strip">
          {examples.map(([route, title, kind]) => (
            <div key={route}><span>{route}</span><div><strong>{title}</strong><small>{kind}</small></div></div>
          ))}
        </section>
      </main>

      <Modal title="创建研究项目" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="title" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="例如：大学生 AI 焦虑研究" />
          </Form.Item>
          <Form.Item name="idea_text" label="研究想法" rules={[{ required: true, min: 4, message: '请描述研究想法' }]}>
            <Input.TextArea rows={5} placeholder="用自然语言描述对象、变量和你想研究的关系……" />
          </Form.Item>
          <Button block type="primary" htmlType="submit" size="large" loading={submitting}>创建并进入研究</Button>
        </Form>
      </Modal>
    </div>
  )
}
