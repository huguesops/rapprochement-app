"""
Génération de rapports: Excel détail, CSV suspens, PDF formel
"""

import pandas as pd
import streamlit as st
from io import BytesIO
from datetime import datetime
from pathlib import Path

# ReportLab pour PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image
)
from reportlab.lib.units import mm, cm

from modules.db_manager import (
    get_matches, get_suspens, get_stats, get_stats_for_entite,
    get_all_mappages, get_active_session
)
from modules.utils import formater_montant, formater_date


def export_excel_detail(session_id: int) -> BytesIO:
    """
    Génère un fichier Excel avec 1 sheet par entité + synthèse.
    """
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # Formatage
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#1E88E5', 'font_color': 'white',
            'border': 1, 'text_wrap': True
        })
        money_format = workbook.add_format({'num_format': '#,##0', 'border': 1})
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy', 'border': 1})
        text_format = workbook.add_format({'border': 1, 'text_wrap': True})
        
        # Sheet Synthèse
        stats = get_stats(session_id)
        synth_data = []
        entites = ['DISTRIBUTION', 'NUTRITION', 'SERVICES', 'ÉLEVAGE']
        
        for entite in entites:
            nb_matches = stats.get('matches_par_entite', {}).get(entite, 0)
            nb_suspens = stats.get('suspens_par_entite', {}).get(entite, 0)
            total = nb_matches + nb_suspens
            taux = round(nb_matches / max(total, 1) * 100, 1) if total > 0 else 0
            synth_data.append([entite, total, nb_matches, nb_suspens, f"{taux}%"])
        
        synth_data.append([
            'TOTAL GROUPE',
            sum(row[1] for row in synth_data),
            sum(row[2] for row in synth_data),
            sum(row[3] for row in synth_data),
            f"{round(sum(row[2] for row in synth_data) / max(sum(row[1] for row in synth_data), 1) * 100, 1)}%"
        ])
        
        df_synth = pd.DataFrame(
            synth_data,
            columns=['Entité', 'Total Opérations', 'Appairés', 'Suspens', '% OK']
        )
        df_synth.to_excel(writer, sheet_name='SYNTHÈSE', index=False, startrow=1)
        
        # En-tête synthèse
        ws_synth = writer.sheets['SYNTHÈSE']
        ws_synth.write(0, 0, f"Rapport de Rapprochement Bancaire - Groupe SKAB - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                      workbook.add_format({'bold': True, 'font_size': 14}))
        
        for col_num, value in enumerate(df_synth.columns.values):
            ws_synth.write(1, col_num, value, header_format)
        
        # Sheets par entité
        for entite in entites:
            # Matches
            matches = get_matches(session_id, entite)
            if matches:
                df_m = pd.DataFrame(matches)
                cols = ['date_operation', 'banque', 'libelle_releve', 'libelle_gl',
                       'montant', 'type_match', 'confiance', 'gl_piece', 'gl_compte']
                cols = [c for c in cols if c in df_m.columns]
                df_m = df_m[cols]
                df_m.columns = ['Date', 'Banque', 'Libellé Relevé', 'Libellé GL',
                               'Montant', 'Type Match', 'Confiance', 'Pièce GL', 'Compte GL']
                df_m.to_excel(writer, sheet_name=f'{entite}_MATCHES', index=False, startrow=1)
                
                ws = writer.sheets[f'{entite}_MATCHES']
                ws.write(0, 0, f"Appairages - {entite}", 
                        workbook.add_format({'bold': True, 'font_size': 12}))
                for col_num, value in enumerate(df_m.columns.values):
                    ws.write(1, col_num, value, header_format)
            
            # Suspens
            suspens = get_suspens(session_id, entite)
            if suspens:
                df_s = pd.DataFrame(suspens)
                cols = ['date_operation', 'type_suspens', 'source', 'libelle',
                       'montant', 'banque', 'motif', 'observations', 'statut']
                cols = [c for c in cols if c in df_s.columns]
                df_s = df_s[cols]
                df_s.columns = ['Date', 'Type', 'Source', 'Libellé',
                               'Montant', 'Banque', 'Motif', 'Observations', 'Statut']
                df_s.to_excel(writer, sheet_name=f'{entite}_SUSPENS', index=False, startrow=1)
                
                ws = writer.sheets[f'{entite}_SUSPENS']
                ws.write(0, 0, f"Suspens - {entite}",
                        workbook.add_format({'bold': True, 'font_size': 12}))
                for col_num, value in enumerate(df_s.columns.values):
                    ws.write(1, col_num, value, header_format)
    
    output.seek(0)
    return output


def export_suspens_csv(session_id: int) -> BytesIO:
    """
    Génère un CSV des suspens pour investigation.
    """
    suspens = get_suspens(session_id)
    if not suspens:
        return BytesIO()
    
    df = pd.DataFrame(suspens)
    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', sep=';')
    output.seek(0)
    return output


def generer_pdf_rapport(session_id: int) -> BytesIO:
    """
    Génère un rapport PDF formel avec signature.
    """
    output = BytesIO()
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=18, spaceAfter=20, textColor=colors.HexColor('#1E88E5')
    )
    heading_style = ParagraphStyle(
        'CustomHeading', parent=styles['Heading2'],
        fontSize=14, spaceAfter=10, textColor=colors.HexColor('#333333')
    )
    normal_style = ParagraphStyle(
        'CustomNormal', parent=styles['Normal'],
        fontSize=10, spaceAfter=6
    )
    
    # Document
    doc = SimpleDocTemplate(
        output, pagesize=A4,
        topMargin=2*cm, bottomMargin=2*cm,
        leftMargin=2*cm, rightMargin=2*cm
    )
    
    elements = []
    
    # En-tête
    elements.append(Paragraph(
        "GROUPE SKAB CAMEROUN", title_style
    ))
    elements.append(Paragraph(
        "Rapport de Rapprochement Bancaire", heading_style
    ))
    elements.append(Paragraph(
        f"Date d'édition: {datetime.now().strftime('%d/%m/%Y à %H:%M')}", normal_style
    ))
    elements.append(Spacer(1, 0.5*cm))
    
    # Statistiques globales
    stats = get_stats(session_id)
    elements.append(Paragraph("Synthèse Globale", heading_style))
    
    total_ops = stats.get('total_matches', 0) + stats.get('total_suspens', 0)
    taux_global = round(stats.get('total_matches', 0) / max(total_ops, 1) * 100, 1)
    
    synth_data = [
        ['Indicateur', 'Valeur'],
        ['Total appairages', str(stats.get('total_matches', 0))],
        ['Total suspens', str(stats.get('total_suspens', 0))],
        ['Taux d\'appairage', f"{taux_global}%"],
        ['Relevés chargés', str(stats.get('total_releves', 0))],
    ]
    
    t_synth = Table(synth_data, colWidths=[200, 150])
    t_synth.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E88E5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
    ]))
    elements.append(t_synth)
    elements.append(Spacer(1, 0.5*cm))
    
    # Détail par entité
    elements.append(Paragraph("Détail par Entité", heading_style))
    
    entites = ['DISTRIBUTION', 'NUTRITION', 'SERVICES', 'ÉLEVAGE']
    detail_data = [['Entité', 'Appairés', 'Suspens', 'Total', 'Taux']]
    
    for entite in entites:
        nb_matches = stats.get('matches_par_entite', {}).get(entite, 0)
        nb_suspens = stats.get('suspens_par_entite', {}).get(entite, 0)
        total_e = nb_matches + nb_suspens
        taux_e = round(nb_matches / max(total_e, 1) * 100, 1)
        detail_data.append([
            entite, str(nb_matches), str(nb_suspens),
            str(total_e), f"{taux_e}%"
        ])
    
    # Total
    total_m = sum(int(r[1]) for r in detail_data[1:])
    total_s = sum(int(r[2]) for r in detail_data[1:])
    total_t = total_m + total_s
    taux_t = round(total_m / max(total_t, 1) * 100, 1)
    detail_data.append(['TOTAL', str(total_m), str(total_s), str(total_t), f"{taux_t}%"])
    
    t_detail = Table(detail_data, colWidths=[120, 80, 80, 80, 80])
    t_detail.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E88E5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F5F5F5')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E3F2FD')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(t_detail)
    elements.append(Spacer(1, 1*cm))
    
    # Suspens par motif
    elements.append(Paragraph("Répartition des Suspens par Motif", heading_style))
    suspens_motifs = stats.get('suspens_par_motif', {})
    if suspens_motifs:
        motif_data = [['Motif', 'Nombre']]
        for motif, count in suspens_motifs.items():
            motif_data.append([motif, str(count)])
        
        t_motif = Table(motif_data, colWidths=[300, 100])
        t_motif.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E88E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(t_motif)
    
    elements.append(Spacer(1, 1.5*cm))
    
    # Signature
    elements.append(Paragraph("Approbation", heading_style))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("Validé par: ___________________________", normal_style))
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph(f"Date: {datetime.now().strftime('%d/%m/%Y')}", normal_style))
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph("Cachet & Signature:", normal_style))
    
    # Footer
    elements.append(Spacer(1, 2*cm))
    elements.append(Paragraph(
        f"Document généré automatiquement par l'application de rapprochement bancaire SKAB - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle('Footer', parent=normal_style, fontSize=8, textColor=colors.grey)
    ))
    
    doc.build(elements)
    output.seek(0)
    return output


def afficher_boutons_exports(session_id: int):
    """Affiche les boutons d'export dans l'onglet 5."""
    st.subheader("📤 Exports disponibles")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📊 Export Excel Détail", use_container_width=True):
            with st.spinner("Génération du fichier Excel..."):
                excel_data = export_excel_detail(session_id)
                st.download_button(
                    label="⬇️ Télécharger Excel",
                    data=excel_data,
                    file_name=f"rapprochement_skab_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
    
    with col2:
        if st.button("⚠️ Export Suspens CSV", use_container_width=True):
            with st.spinner("Génération du fichier CSV..."):
                csv_data = export_suspens_csv(session_id)
                if csv_data.getvalue():
                    st.download_button(
                        label="⬇️ Télécharger CSV",
                        data=csv_data,
                        file_name=f"suspens_skab_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                else:
                    st.info("Aucun suspens à exporter.")
    
    with col3:
        if st.button("📄 Générer PDF Formel", use_container_width=True):
            with st.spinner("Génération du rapport PDF..."):
                pdf_data = generer_pdf_rapport(session_id)
                st.download_button(
                    label="⬇️ Télécharger PDF",
                    data=pdf_data,
                    file_name=f"rapport_rapprochement_skab_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )