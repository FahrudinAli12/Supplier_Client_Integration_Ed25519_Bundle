/**
 * RFID Linen Pro — Manajemen Rumah Sakit
 *
 * Master Data Management for target hospitals (Rumah Sakit) and Client Accounts.
 * Operates under Supplier Master Authority without requiring human login.
 * Unifies hospital master CRUD, status toggle, and Client account credentials.
 */

import { api } from '../api.js';
import { showSuccessToast } from '../shell.js';

export const rumahSakitPage = {
    render() {
        return `
<div x-data="rumahSakitData()" x-init="initialize()">
    <!-- Glass Panel Container -->
    <div class="glass-panel rounded-2xl border border-glass-border shadow-sm w-full overflow-hidden flex flex-col">
        <!-- Header Controls -->
        <div class="p-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-glass-border">
            <div>
                <div class="flex items-center gap-2">
                    <h1 class="font-headline-lg font-bold text-primary text-2xl">Manajemen Rumah Sakit</h1>
                    <span class="px-2.5 py-0.5 bg-primary/10 text-primary font-bold rounded-full text-label-sm">Admin Cloud</span>
                </div>
                <p class="font-body-md text-on-surface-variant">Kelola akun dan data Rumah Sakit tujuan pengiriman linen.</p>
            </div>
            <div class="flex items-center gap-3">
                <button @click="openAddModal()" class="bg-primary hover:bg-primary/90 text-on-primary font-label-lg px-5 py-2.5 rounded-full shadow-md transition-all flex items-center gap-2">
                    <span class="material-symbols-outlined text-[20px]">add</span>
                    Tambah Rumah Sakit
                </button>
            </div>
        </div>

        <!-- Table -->
        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-white/40 text-on-surface-variant font-label-md border-b border-glass-border">
                        <th class="py-3 px-6">Kode RS</th>
                        <th class="py-3 px-6">Nama Rumah Sakit</th>
                        <th class="py-3 px-6">Alamat</th>
                        <th class="py-3 px-6">Kontak</th>
                        <th class="py-3 px-6">Email</th>
                        <th class="py-3 px-6 text-right">Aksi</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Loading State -->
                    <template x-if="loading">
                        <tr>
                            <td colspan="6" class="py-8 text-center text-on-surface-variant">
                                <div class="flex items-center justify-center gap-3">
                                    <div class="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                                    Memuat data rumah sakit...
                                </div>
                            </td>
                        </tr>
                    </template>

                    <!-- Empty State -->
                    <template x-if="!loading && items.length === 0">
                        <tr>
                            <td colspan="6" class="py-8 text-center text-on-surface-variant">
                                Belum ada data rumah sakit terdaftar. Klik 'Tambah Rumah Sakit' untuk membuat baru.
                            </td>
                        </tr>
                    </template>

                    <!-- Data Rows -->
                    <template x-for="item in items" :key="item.rs_id || item.kode_rs">
                        <tr class="border-b border-glass-border/50 hover:bg-white/20 transition-colors">
                            <td class="py-3.5 px-6 font-data-mono font-bold text-primary" x-text="item.kode_rs"></td>
                            <td class="py-3.5 px-6 font-body-md font-semibold" x-text="item.nama_rs"></td>
                            <td class="py-3.5 px-6 font-body-md text-on-surface-variant" x-text="item.alamat || '-'"></td>
                            <td class="py-3.5 px-6 font-body-md text-on-surface-variant" x-text="item.kontak || '-'"></td>
                            <td class="py-3.5 px-6 font-body-md text-on-surface-variant" x-text="item.client_email || item.email || '-'"></td>
                            <td class="py-3.5 px-6 text-right font-label-md">
                                <button @click="openEditModal(item)" class="text-primary hover:underline mr-4">Edit</button>
                                <button @click="confirmDelete(item)" class="text-status-error hover:underline" x-text="item.is_active ? 'Hapus' : 'Aktifkan'"></button>
                            </td>
                        </tr>
                    </template>
                </tbody>
            </table>
        </div>

        <!-- Error State -->
        <template x-if="fetchError">
            <div class="p-6 text-center text-status-error font-body-md" x-text="'Error: ' + fetchError"></div>
        </template>
    </div>

    <!-- ═══ Modal Form (Tambah / Edit) ═══ -->
    <div x-show="showModal"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[150] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;"
         @keydown.escape.window="closeModal()">
        <div @click.outside="closeModal()"
             x-transition:enter="transition ease-out duration-200"
             x-transition:enter-start="opacity-0 scale-95"
             x-transition:enter-end="opacity-100 scale-100"
             class="bg-surface/95 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4">
            <h2 class="font-headline-md font-bold text-primary text-xl" x-text="editMode ? 'Edit Rumah Sakit' : 'Tambah Rumah Sakit Baru'"></h2>
            <form @submit.prevent="handleSubmit()" class="flex flex-col gap-3">
                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-sm text-on-surface">Kode RS <span class="text-status-error">*</span></label>
                    <input x-model="form.kode_rs" type="text" required placeholder="e.g. RS-001"
                           class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 font-data-mono font-bold" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-sm text-on-surface">Nama Rumah Sakit <span class="text-status-error">*</span></label>
                    <input x-model="form.nama_rs" type="text" required placeholder="misal: RSUD dr. Soetomo"
                           class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-sm text-on-surface">Alamat</label>
                    <input x-model="form.alamat" type="text" placeholder="Alamat lengkap..."
                           class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-sm text-on-surface">Kontak / Telepon</label>
                    <input x-model="form.kontak" type="text" placeholder="08123456789"
                           class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-sm text-on-surface">Email</label>
                    <input x-model="form.email" type="email" placeholder="admin@rs.com"
                           class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-sm text-on-surface">Password <span class="text-status-error" x-show="!editMode">*</span></label>
                    <input x-model="form.password" type="password" minlength="6" :required="!editMode"
                           :placeholder="editMode ? 'Kosongkan jika password tidak diubah' : 'Masukkan password akun RS'"
                           class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50" />
                </div>

                <div class="flex justify-end gap-3 mt-4">
                    <button type="button" @click="closeModal()" class="px-5 py-2 rounded-full border border-glass-border text-label-lg hover:bg-white/50 transition-colors">Batal</button>
                    <button type="submit" class="bg-primary text-on-primary px-6 py-2 rounded-full font-label-lg shadow-md hover:bg-primary/90 transition-colors"
                            :disabled="submitting">
                        <span x-show="!submitting">Simpan</span>
                        <span x-show="submitting" class="flex items-center gap-2">
                            <span class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                            Menyimpan...
                        </span>
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- ═══ Modal Konfirmasi Status (Aktif / Nonaktif) ═══ -->
    <div x-show="showDeleteConfirm"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[150] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;"
         @keydown.escape.window="showDeleteConfirm = false">
        <div @click.outside="showDeleteConfirm = false"
             class="bg-surface/90 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4">
            <div class="flex items-center gap-3 text-status-error">
                <span class="material-symbols-outlined text-[28px]">warning</span>
                <h3 class="font-headline-md font-bold" x-text="deleteTarget?.is_active ? 'Nonaktifkan Rumah Sakit?' : 'Aktifkan Rumah Sakit?'"></h3>
            </div>
            <p class="font-body-md text-on-surface-variant">
                <span x-text="deleteTarget?.is_active ? 'Rumah sakit berikut akan dinonaktifkan. Kontrak dan histori pengiriman tetap tersimpan.' : 'Rumah sakit berikut akan diaktifkan kembali.'"></span>
                <strong class="text-on-surface" x-text="deleteTarget?.nama_rs"></strong>.
            </p>
            <div class="flex justify-end gap-3 mt-2">
                <button @click="showDeleteConfirm = false" class="px-5 py-2 rounded-full border border-glass-border text-label-lg hover:bg-white/50 transition-colors">Batal</button>
                <button @click="executeDelete()" class="bg-status-error text-white px-6 py-2 rounded-full font-label-lg shadow-md hover:bg-status-error/90 transition-colors"
                        :disabled="submitting">
                    <span x-text="deleteTarget?.is_active ? 'Nonaktifkan' : 'Aktifkan'"></span>
                </button>
            </div>
        </div>
    </div>

    <!-- ═══ Modal Error (e.g. 503 Supabase Offline / 409 conflict) ═══ -->
    <div x-show="errorModal.show"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[200] bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;">
        <div class="bg-surface/90 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4 text-on-surface">
            <div class="flex items-center gap-3 text-status-error">
                <span class="material-symbols-outlined text-[28px]">error</span>
                <h3 class="font-headline-md font-bold" x-text="errorModal.title"></h3>
            </div>
            <p class="font-body-md text-on-surface-variant" x-text="errorModal.message"></p>
            <div class="flex justify-end mt-2">
                <button @click="errorModal.show = false" class="bg-primary text-on-primary font-label-lg px-6 py-2 rounded-full hover:bg-primary/90 transition-colors">Tutup</button>
            </div>
        </div>
    </div>
</div>
        `;
    },

    mount() {},
    unmount() {},
};

export function registerRumahSakitComponent() {
    if (window.Alpine && !window._rumahSakitRegistered) {
        window.Alpine.data('rumahSakitData', () => ({
            items: [],
            loading: true,
            fetchError: null,

            showModal: false,
            showDeleteConfirm: false,
            editMode: false,
            submitting: false,
            form: { kode_rs: '', nama_rs: '', alamat: '', kontak: '', email: '', password: '' },
            editId: null,
            deleteTarget: null,
            errorModal: { show: false, title: '', message: '' },

            async initialize() {
                await this.fetchList();
            },

            async fetchList() {
                this.loading = true;
                this.fetchError = null;
                try {
                    const resp = await api.getRumahSakitList();
                    if (!resp.ok) throw new Error(resp.data?.detail || 'Gagal mengambil data rumah sakit');
                    this.items = resp.data || [];
                } catch (err) {
                    console.error(err);
                    this.fetchError = err.message;
                } finally {
                    this.loading = false;
                }
            },

            openAddModal() {
                this.editMode = false;
                this.editId = null;
                this.form = { kode_rs: '', nama_rs: '', alamat: '', kontak: '', email: '', password: '' };
                this.showModal = true;
            },

            openEditModal(item) {
                this.editMode = true;
                this.editId = item.rs_id || item.id;
                this.form = {
                    kode_rs: item.kode_rs,
                    nama_rs: item.nama_rs,
                    alamat: item.alamat || '',
                    kontak: item.kontak || '',
                    email: item.client_email || item.email || '',
                    password: '',
                };
                this.showModal = true;
            },

            closeModal() {
                this.showModal = false;
            },

            async handleSubmit() {
                this.submitting = true;
                const payload = {
                    kode_rs: this.form.kode_rs.trim(),
                    nama_rs: this.form.nama_rs.trim(),
                    alamat: this.form.alamat?.trim() || null,
                    kontak: this.form.kontak?.trim() || null,
                    email: this.form.email?.trim() || null,
                    client_email: this.form.email?.trim() || null,
                };
                if (this.form.password?.trim()) {
                    payload.password = this.form.password.trim();
                    payload.client_password = this.form.password.trim();
                }
                try {
                    const resp = this.editMode
                        ? await api.updateRumahSakit(this.editId, payload)
                        : await api.createRumahSakit(payload);
                    if (!resp.ok) {
                        this.errorModal = {
                            show: true,
                            title: resp.status === 503 ? 'Cloud Supabase Offline' : 'Gagal Menyimpan Rumah Sakit',
                            message: resp.data?.detail || 'Terjadi kesalahan pada server.',
                        };
                        return;
                    }
                    showSuccessToast(this.editMode ? 'Data Rumah Sakit berhasil diperbarui!' : 'Rumah Sakit baru berhasil didaftarkan!');
                    this.closeModal();
                    await this.fetchList();
                } catch (e) {
                    this.errorModal = { show: true, title: 'Error', message: 'Gagal menghubungi server.' };
                } finally {
                    this.submitting = false;
                }
            },

            confirmDelete(item) {
                this.deleteTarget = item;
                this.showDeleteConfirm = true;
            },

            async executeDelete() {
                if (!this.deleteTarget) return;
                this.submitting = true;
                const targetId = this.deleteTarget.rs_id || this.deleteTarget.id;
                const wasActive = Boolean(this.deleteTarget.is_active);
                try {
                    const resp = wasActive
                        ? await api.deleteRumahSakit(targetId)
                        : await api.updateRumahSakit(targetId, { is_active: true });
                    if (!resp.ok) {
                        this.showDeleteConfirm = false;
                        this.errorModal = {
                            show: true,
                            title: resp.status === 503 ? 'Cloud Supabase Offline' : 'Gagal Mengubah Status Rumah Sakit',
                            message: resp.data?.detail || 'Status rumah sakit tidak dapat diubah.',
                        };
                        return;
                    }
                    showSuccessToast(wasActive ? 'Rumah sakit berhasil dinonaktifkan.' : 'Rumah sakit berhasil diaktifkan kembali.');
                    this.showDeleteConfirm = false;
                    this.deleteTarget = null;
                    await this.fetchList();
                } catch (e) {
                    this.showDeleteConfirm = false;
                    this.errorModal = { show: true, title: 'Error', message: 'Gagal menghubungi server.' };
                } finally {
                    this.submitting = false;
                }
            },
        }));
        window._rumahSakitRegistered = true;
    }
}
