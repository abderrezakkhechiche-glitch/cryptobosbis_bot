import os
import asyncio
import tempfile
import io
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import PyPDF2
from pdf2image import convert_from_path
from docx import Document
from PIL import Image, ImageDraw, ImageFont
import pikepdf
import img2pdf

# ------------------- الإعدادات -------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")  # اختياري

# تخزين مؤقت لملفات المستخدمين
user_files = {}

# ------------------- قائمة الخدمات -------------------
SERVICES = {
    "merge": "🔗 دمج PDF",
    "split": "✂️ تقسيم PDF",
    "compress": "🗜️ ضغط PDF",
    "pdf2word": "📝 PDF → Word",
    "word2pdf": "📄 Word → PDF",
    "watermark": "💧 إضافة علامة مائية",
    "protect": "🔐 حماية بكلمة مرور",
    "unlock": "🔓 إزالة كلمة المرور",
    "rotate": "🔄 تدوير الصفحات",
    "extract_images": "🖼️ استخراج الصور"
}

# ------------------- دالة البداية -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = f"""
📚 **مرحباً بك في بوت PDF الشامل** 📚

🇩🇿 أنا بوتك العربي المتكامل لمعالجة ملفات PDF.

**🔹 الخدمات المتوفرة:**
"""
    for service in SERVICES.values():
        welcome += f"   {service}\n"
    
    welcome += """
🔹 **كيفية الاستخدام:**
1. اختر الخدمة من القائمة أدناه
2. أرسل الملف/الملفات المطلوبة
3. انتظر النتيجة

✨ أرسل /services لعرض القائمة
"""
    
    await show_services(update, context)

# ------------------- عرض الخدمات -------------------
async def show_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    row = []
    for i, (key, name) in enumerate(SERVICES.items()):
        row.append(InlineKeyboardButton(name, callback_data=key))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("🔍 **اختر الخدمة التي تريدها:**", reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.message.edit_text("🔍 **اختر الخدمة التي تريدها:**", reply_markup=reply_markup, parse_mode='Markdown')

# ------------------- معالجة اختيار الخدمة -------------------
async def service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    service = query.data
    user_id = update.effective_user.id
    user_files[user_id] = {'service': service, 'files': []}
    
    service_name = SERVICES.get(service, service)
    
    messages = {
        "merge": "📤 أرسل لي **ملفات PDF** التي تريد دمجها (يمكنك إرسال عدة ملفات واحدة تلو الأخرى).\n\nعند الانتهاء، أرسل /done",
        "split": "📤 أرسل ملف PDF الذي تريد تقسيمه.",
        "compress": "📤 أرسل ملف PDF الذي تريد ضغطه.",
        "pdf2word": "📤 أرسل ملف PDF لتحويله إلى Word.",
        "word2pdf": "📤 أرسل ملف Word لتحويله إلى PDF.",
        "watermark": "📤 أرسل ملف PDF ثم النص الذي تريد إضافته كعلامة مائية.",
        "protect": "📤 أرسل ملف PDF وكلمة المرور التي تريد إضافتها.",
        "unlock": "📤 أرسل ملف PDF المحمي بكلمة مرور.",
        "rotate": "📤 أرسل ملف PDF الذي تريد تدوير صفحاته.",
        "extract_images": "📤 أرسل ملف PDF لاستخراج الصور منه."
    }
    
    await query.edit_message_text(f"🔄 **{service_name}**\n\n{messages.get(service, 'أرسل الملف المطلوب.')}", parse_mode='Markdown')

# ------------------- معالجة استقبال الملفات -------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_files:
        await update.message.reply_text("❌ الرجاء اختيار خدمة أولاً عبر /services")
        return
    
    service = user_files[user_id]['service']
    document = update.message.document
    
    if not document.file_name.lower().endswith(('.pdf', '.docx', '.doc')):
        await update.message.reply_text("❌ هذا النوع من الملفات غير مدعوم. الرجاء إرسال PDF أو Word.")
        return
    
    # تحميل الملف
    file = await document.get_file()
    file_bytes = io.BytesIO()
    await file.download_to_memory(file_bytes)
    file_bytes.seek(0)
    
    # حفظ الملف مؤقتاً
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(document.file_name)[1]) as tmp:
        tmp.write(file_bytes.read())
        tmp_path = tmp.name
    
    user_files[user_id]['files'].append(tmp_path)
    
    if service == "merge":
        await update.message.reply_text(f"✅ تم استلام الملف. أرسل المزيد أو اكتب /done للدمج")
    else:
        # خدمات تحتاج ملف واحد فقط
        await process_file(update, user_id, service, user_files[user_id]['files'][0])
        del user_files[user_id]

# ------------------- معالجة الأمر /done -------------------
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_files or user_files[user_id]['service'] != "merge":
        await update.message.reply_text("❌ لا توجد عملية دمج نشطة.")
        return
    
    files = user_files[user_id]['files']
    if len(files) < 2:
        await update.message.reply_text("❌ يجب إرسال ملفين على الأقل للدمج.")
        return
    
    await process_merge(update, user_id, files)
    del user_files[user_id]

# ------------------- دمج PDF -------------------
async def process_merge(update: Update, user_id, files):
    processing = await update.message.reply_text("🔄 جاري دمج الملفات...")
    
    try:
        merger = PyPDF2.PdfMerger()
        for file_path in files:
            merger.append(file_path)
        
        output = io.BytesIO()
        merger.write(output)
        output.seek(0)
        
        await update.message.reply_document(
            document=output,
            filename="merged.pdf",
            caption="✅ تم دمج الملفات بنجاح!"
        )
        
        for file_path in files:
            os.unlink(file_path)
        
        await processing.delete()
        
    except Exception as e:
        await processing.edit_text(f"❌ خطأ أثناء الدمج: {str(e)[:100]}")

# ------------------- معالجة الملف حسب الخدمة -------------------
async def process_file(update: Update, user_id, service, file_path):
    processing = await update.message.reply_text("🔄 جاري المعالجة...")
    
    try:
        output = io.BytesIO()
        output_filename = ""
        
        if service == "split":
            reader = PyPDF2.PdfReader(file_path)
            for i, page in enumerate(reader.pages):
                writer = PyPDF2.PdfWriter()
                writer.add_page(page)
                page_output = io.BytesIO()
                writer.write(page_output)
                page_output.seek(0)
                await update.message.reply_document(
                    document=page_output,
                    filename=f"page_{i+1}.pdf"
                )
            await processing.edit_text("✅ تم تقسيم الملف بنجاح!")
            os.unlink(file_path)
            return
            
        elif service == "compress":
            # ضغط PDF
            with pikepdf.open(file_path) as pdf:
                pdf.save(output, compress_streams=True)
            output_filename = "compressed.pdf"
            
        elif service == "pdf2word":
            from pdf2docx import Converter
            with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
                cv = Converter(file_path)
                cv.convert(tmp.name)
                cv.close()
                with open(tmp.name, 'rb') as f:
                    output.write(f.read())
                os.unlink(tmp.name)
            output_filename = "converted.docx"
            
        elif service == "word2pdf":
            from docx2pdf import convert
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                convert(file_path, tmp.name)
                with open(tmp.name, 'rb') as f:
                    output.write(f.read())
                os.unlink(tmp.name)
            output_filename = "converted.pdf"
            
        elif service == "extract_images":
            images = convert_from_path(file_path)
            for i, img in enumerate(images):
                img_output = io.BytesIO()
                img.save(img_output, format='JPEG')
                img_output.seek(0)
                await update.message.reply_document(
                    document=img_output,
                    filename=f"page_{i+1}.jpg"
                )
            await processing.edit_text(f"✅ تم استخراج {len(images)} صورة!")
            os.unlink(file_path)
            return
            
        else:
            await processing.edit_text("❌ هذه الخدمة قيد التطوير")
            os.unlink(file_path)
            return
        
        output.seek(0)
        await update.message.reply_document(
            document=output,
            filename=output_filename,
            caption="✅ تمت المعالجة بنجاح!"
        )
        
        os.unlink(file_path)
        await processing.delete()
        
    except Exception as e:
        await processing.edit_text(f"❌ خطأ: {str(e)[:100]}")
        try:
            os.unlink(file_path)
        except:
            pass

# ------------------- الدالة الرئيسية -------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("services", show_services))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CallbackQueryHandler(service_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("✅ PDF Bot started successfully")
    app.run_polling()

if __name__ == "__main__":
    main()